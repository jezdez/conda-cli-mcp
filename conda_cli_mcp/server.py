from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from mcp import MCPError
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    INVALID_PARAMS,
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
    ToolAnnotations,
)

from . import __version__

if TYPE_CHECKING:
    from typing import Any, Final

    from mcp.server import ServerRequestContext
    from mcp.types import CallToolRequestParams, PaginatedRequestParams

    from .execution import CondaExecutor

EXECUTE_TOOL_NAME: Final = "conda_execute"
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
EXECUTE_INPUT_SCHEMA: Final[dict[str, Any]] = {
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
            "description": "Per-command timeout override.",
        },
    },
    "required": ["argv"],
    "additionalProperties": False,
}


class CondaMCPServer:
    """MCP application exposing one conda executor."""

    def __init__(self, executor: CondaExecutor) -> None:
        self.executor = executor
        self.execute_tool = Tool(
            name=EXECUTE_TOOL_NAME,
            description="Run an argument vector with the configured conda executable.",
            input_schema=EXECUTE_INPUT_SCHEMA,
            output_schema=EXECUTION_OUTPUT_SCHEMA,
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=True,
                idempotent_hint=False,
                open_world_hint=True,
            ),
        )
        self.input_validator = Draft202012Validator(EXECUTE_INPUT_SCHEMA)
        self.output_validator = Draft202012Validator(EXECUTION_OUTPUT_SCHEMA)
        self.server = Server(
            "conda-cli-mcp",
            version=__version__,
            on_list_tools=self.list_tools,
            on_call_tool=self.call_tool,
        )

    async def list_tools(
        self,
        _context: ServerRequestContext,
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        """List the raw phase-one execution tool."""
        return ListToolsResult(tools=[self.execute_tool])

    async def execute(self, arguments: dict[str, Any]) -> CallToolResult:
        """Validate an MCP request and execute conda."""
        try:
            self.input_validator.validate(arguments)
        except ValidationError as error:
            raise MCPError(INVALID_PARAMS, error.message) from error

        result = await self.executor.execute(
            arguments["argv"],
            cwd=Path(arguments["cwd"]) if "cwd" in arguments else None,
            stdin=arguments.get("stdin"),
            timeout_seconds=arguments.get("timeout_seconds"),
        )
        structured = result.as_dict()
        self.output_validator.validate(structured)
        return CallToolResult(
            content=[TextContent(text=result.summary())],
            structured_content=structured,
            is_error=result.failed,
        )

    async def call_tool(
        self,
        _context: ServerRequestContext,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        """Dispatch a low-level MCP tool request."""
        if params.name != EXECUTE_TOOL_NAME:
            raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}")
        return await self.execute(params.arguments or {})

    async def run_stdio(self) -> None:
        """Serve MCP over standard input and standard output."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )
