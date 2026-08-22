from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from mcp import MCPError
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    CallToolResult,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
    Resource,
    TextContent,
    TextResourceContents,
    Tool,
    ToolAnnotations,
)

from . import __version__
from .capabilities import plugin_fingerprint
from .command import command_tools
from .execution import CompletionQueryError
from .policy import PolicyViolation, SafetyPolicy

if TYPE_CHECKING:
    from typing import Any, Final

    from mcp.server import ServerRequestContext
    from mcp.types import (
        CallToolRequestParams,
        PaginatedRequestParams,
        ReadResourceRequestParams,
    )

    from .capabilities import Capabilities
    from .execution import CondaExecutor
    from .models import ExecutionResult
    from .policy import OperationPolicy

CAPABILITIES_URI: Final = "conda://capabilities"
EXECUTE_TOOL_NAME: Final = "conda_execute"
COMPLETION_TOOL_NAME: Final = "conda_cli_command"
COMPLETION_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "command_path": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "pattern": "^(?!-)(?!.*\\s).+$",
            },
            "description": "Canonical conda command path without the executable.",
            "default": [],
        }
    },
    "additionalProperties": False,
}
COMPLETION_OUTPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "availability": {
            "type": "string",
            "enum": ["available", "not_installed", "not_generated", "unavailable"],
        },
        "requested_command_path": {"type": "array", "items": {"type": "string"}},
        "resolved_command_path": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "alias_target": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "command": {"type": ["object", "null"]},
        "manifest": {"type": ["object", "null"]},
        "hint": {"type": ["string", "null"]},
    },
    "required": [
        "availability",
        "requested_command_path",
        "resolved_command_path",
        "alias_target",
        "command",
        "manifest",
        "hint",
    ],
    "additionalProperties": False,
}
EXECUTION_OUTPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "exit_code": {"type": ["integer", "null"]},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "duration_ms": {"type": "integer", "minimum": 0},
        "parsed_json": {},
        "timed_out": {"type": "boolean"},
        "cancelled": {"type": "boolean"},
        "stdout_truncated": {"type": "boolean"},
        "stderr_truncated": {"type": "boolean"},
        "restart_required": {"type": "boolean"},
    },
    "required": [
        "exit_code",
        "stdout",
        "stderr",
        "duration_ms",
        "parsed_json",
        "timed_out",
        "cancelled",
        "stdout_truncated",
        "stderr_truncated",
        "restart_required",
    ],
    "additionalProperties": False,
}


def execution_input_schema(maximum_timeout_seconds: float) -> dict[str, Any]:
    """Return the raw execution schema for one immutable server policy."""
    return {
        "type": "object",
        "properties": {
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Arguments passed directly to conda.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the conda process.",
            },
            "stdin": {
                "type": "string",
                "description": "Bounded non-interactive input for the conda process.",
            },
            "timeout_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": maximum_timeout_seconds,
                "description": "Per-command timeout no greater than the server limit.",
            },
        },
        "required": ["argv"],
        "additionalProperties": False,
    }


class CondaMCPServer:
    """MCP application exposing one conda executor."""

    def __init__(
        self,
        executor: CondaExecutor,
        capabilities: Capabilities | None = None,
        policy: SafetyPolicy = SafetyPolicy(),
    ) -> None:
        self.executor = executor
        self.policy = policy
        self.restart_required = False
        self.capabilities = capabilities
        self.capabilities_json = (
            capabilities.to_json() if capabilities is not None else None
        )
        self.execute_input_schema = execution_input_schema(executor.timeout_seconds)
        self.execute_tool = Tool(
            name=EXECUTE_TOOL_NAME,
            description=(
                "Run raw conda argv with arbitrary arguments. "
                "Mutations also require --allow-write."
            ),
            input_schema=self.execute_input_schema,
            output_schema=EXECUTION_OUTPUT_SCHEMA,
            annotations=self.policy.describe(raw=True).as_tool_annotations(),
        )
        self.input_validator = Draft202012Validator(self.execute_input_schema)
        self.output_validator = Draft202012Validator(EXECUTION_OUTPUT_SCHEMA)
        program = capabilities.program if capabilities is not None else None
        self.generated_tools = (
            {tool.name: tool for tool in command_tools(program)}
            if program is not None
            else {}
        )
        completion_available = capabilities is not None and any(
            plugin.distribution.casefold() == "conda-completion"
            for plugin in capabilities.plugins
        )
        self.completion_tool = (
            Tool(
                name=COMPLETION_TOOL_NAME,
                title="Conda completion command metadata",
                description=(
                    "Read one command from conda-completion's generated metadata."
                ),
                input_schema=COMPLETION_INPUT_SCHEMA,
                output_schema=COMPLETION_OUTPUT_SCHEMA,
                annotations=ToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=False,
                ),
            )
            if completion_available and COMPLETION_TOOL_NAME not in self.generated_tools
            else None
        )
        self.completion_input_validator = Draft202012Validator(COMPLETION_INPUT_SCHEMA)
        self.completion_output_validator = Draft202012Validator(
            COMPLETION_OUTPUT_SCHEMA
        )
        self.server = Server(
            "conda-cli-mcp",
            version=__version__,
            on_list_tools=self.list_tools,
            on_call_tool=self.call_tool,
            on_list_resources=self.list_resources,
            on_read_resource=self.read_resource,
        )

    async def list_resources(
        self,
        _context: ServerRequestContext,
        _params: PaginatedRequestParams | None,
    ) -> ListResourcesResult:
        """List safe metadata for the configured conda installation."""
        if self.capabilities_json is None:
            return ListResourcesResult(resources=[])
        return ListResourcesResult(
            resources=[
                Resource(
                    name="conda_capabilities",
                    title="Conda CLI capabilities",
                    uri=CAPABILITIES_URI,
                    description=(
                        "Startup command catalog and external plugin metadata."
                    ),
                    mime_type="application/json",
                    size=len(self.capabilities_json.encode()),
                )
            ]
        )

    async def read_resource(
        self,
        _context: ServerRequestContext,
        params: ReadResourceRequestParams,
    ) -> ReadResourceResult:
        """Read the immutable startup capability document."""
        if str(params.uri) != CAPABILITIES_URI or self.capabilities_json is None:
            raise MCPError(INVALID_PARAMS, "Unknown resource")
        return ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri=CAPABILITIES_URI,
                    mime_type="application/json",
                    text=self.capabilities_json,
                )
            ]
        )

    async def list_tools(
        self,
        _context: ServerRequestContext,
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        """List the raw executor and discovered structured command tools."""
        tools = [self.execute_tool] if self.policy.allow_exec else []
        if self.completion_tool is not None:
            tools.append(self.completion_tool)
        for command in self.generated_tools.values():
            operation = self.policy.describe(command=command)
            tool = command.as_mcp_tool(output_schema=EXECUTION_OUTPUT_SCHEMA)
            description = tool.description or f"Run conda {' '.join(command.path)}."
            if operation.requires_write:
                description += " May modify environments or files."
            if operation.requires_exec:
                description += " Runs an arbitrary subprocess command."
            tools.append(
                tool.model_copy(
                    update={
                        "annotations": operation.as_tool_annotations(),
                        "description": description,
                    }
                )
            )
        return ListToolsResult(tools=tools)

    async def execute(self, arguments: dict[str, Any]) -> CallToolResult:
        """Validate an MCP request and execute conda."""
        try:
            self.input_validator.validate(arguments)
        except ValidationError as error:
            raise MCPError(
                INVALID_PARAMS,
                f"Invalid arguments at {error.json_path}",
            ) from error

        try:
            operation = self.policy.enforce(arguments["argv"], raw=True)
        except PolicyViolation as error:
            options = " and ".join(error.missing_options)
            raise MCPError(INVALID_REQUEST, f"Operation requires {options}") from error

        try:
            result = await self.executor.execute(
                arguments["argv"],
                cwd=Path(arguments["cwd"]) if "cwd" in arguments else None,
                stdin=arguments.get("stdin"),
                timeout_seconds=arguments.get("timeout_seconds"),
            )
        except (NotADirectoryError, ValueError) as error:
            raise MCPError(INVALID_PARAMS, "Invalid execution options") from error
        return self.format_result(await self.attach_restart_state(result, operation))

    async def inspect_completion_command(
        self,
        arguments: dict[str, Any],
    ) -> CallToolResult:
        """Return one target conda-completion command description."""
        try:
            self.completion_input_validator.validate(arguments)
        except ValidationError as error:
            raise MCPError(
                INVALID_PARAMS,
                f"Invalid arguments at {error.json_path}",
            ) from error
        try:
            payload = await self.executor.inspect_completion_command(
                arguments.get("command_path", ())
            )
        except CompletionQueryError as error:
            message = {
                "invalid_command_path": "Invalid conda command path",
                "unknown_command": "Unknown conda command path",
                "invalid_response": "Conda completion returned invalid metadata",
            }.get(error.code, "Conda completion metadata is unavailable")
            code = (
                INVALID_PARAMS
                if error.code in {"invalid_command_path", "unknown_command"}
                else INVALID_REQUEST
            )
            raise MCPError(code, message) from error
        except (OSError, RuntimeError, ValueError) as error:
            raise MCPError(
                INVALID_REQUEST,
                "Conda completion metadata is unavailable",
            ) from error

        try:
            self.completion_output_validator.validate(payload)
            serialized = json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (ValidationError, ValueError) as error:
            raise MCPError(
                INVALID_REQUEST,
                "Conda completion returned invalid metadata",
            ) from error
        return CallToolResult(
            content=[TextContent(text=serialized)],
            structured_content=payload,
        )

    async def execute_generated(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> CallToolResult:
        """Compile and execute one generated command tool request."""
        tool = self.generated_tools[name]
        try:
            argv = tool.compile(arguments)
        except ValidationError as error:
            raise MCPError(
                INVALID_PARAMS,
                f"Invalid arguments at {error.json_path}",
            ) from error
        try:
            operation = self.policy.enforce(argv, command=tool)
        except PolicyViolation as error:
            options = " and ".join(error.missing_options)
            raise MCPError(INVALID_REQUEST, f"Operation requires {options}") from error
        return self.format_result(
            await self.attach_restart_state(
                await self.executor.execute(argv), operation
            )
        )

    async def attach_restart_state(
        self,
        result: ExecutionResult,
        operation: OperationPolicy,
    ) -> ExecutionResult:
        """Attach stable-server restart state after one completed operation."""
        if (
            not self.restart_required
            and not result.failed
            and not operation.read_only
            and self.capabilities is not None
        ):
            try:
                conda_version, plugins = await self.executor.discover_plugin_state()
            except (OSError, RuntimeError, ValueError):
                self.restart_required = True
            else:
                self.restart_required = (
                    plugin_fingerprint(conda_version, plugins)
                    != self.capabilities.discovery_fingerprint
                )
        return replace(result, restart_required=self.restart_required)

    def format_result(self, result: ExecutionResult) -> CallToolResult:
        """Convert one execution result into the common MCP result envelope."""
        structured = result.as_dict()
        self.output_validator.validate(structured)
        return CallToolResult(
            content=[
                TextContent(text=result.summary()),
                TextContent(
                    text=json.dumps(
                        structured,
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                ),
            ],
            structured_content=structured,
            is_error=result.failed,
        )

    async def call_tool(
        self,
        _context: ServerRequestContext,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        """Dispatch a low-level MCP tool request."""
        arguments = params.arguments or {}
        if params.name == EXECUTE_TOOL_NAME:
            if not self.policy.allow_exec:
                raise MCPError(INVALID_PARAMS, "Unknown tool")
            return await self.execute(arguments)
        if params.name == COMPLETION_TOOL_NAME and self.completion_tool is not None:
            return await self.inspect_completion_command(arguments)
        if params.name in self.generated_tools:
            return await self.execute_generated(params.name, arguments)
        raise MCPError(INVALID_PARAMS, "Unknown tool")

    async def run_stdio(self) -> None:
        """Serve MCP over standard input and standard output."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )
