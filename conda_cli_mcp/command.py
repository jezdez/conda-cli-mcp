from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from mcp.types import Tool

from .models import ActionKind

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from .models import Argument, Command, Program


PASSTHROUGH_ARGUMENT = "args"
TOOL_PREFIX = "conda"


def canonical_tool_name(
    path: tuple[str, ...],
    *,
    disambiguate: bool = False,
) -> str:
    """Return the deterministic MCP name for a canonical conda command path."""
    source_parts = path or ("command",)
    parts = [
        re.sub(r"[^A-Za-z0-9_.-]+", "_", part).strip("_") or "command"
        for part in source_parts
    ]
    natural = "_".join((TOOL_PREFIX, *parts))
    changed = tuple(parts) != source_parts
    if not disambiguate and not changed and len(natural) <= 128:
        return natural

    encoded = json.dumps(path, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()[:10]
    suffix = f"_{digest}"
    stem = natural[: 128 - len(suffix)].rstrip("_.-") or TOOL_PREFIX
    return f"{stem}{suffix}"


def argument_input_schema(argument: Argument) -> dict[str, Any]:
    """Build the JSON Schema for one discovered argparse action."""
    scalar: dict[str, Any] = {
        "type": {
            "string": "string",
            "integer": "integer",
            "number": "number",
        }[argument.value_type]
    }
    if (
        not argument.flags
        and argument.value_type == "string"
        and argument.nargs != "remainder"
    ):
        scalar["pattern"] = "^(?!-)"
    if argument.choices:
        if argument.value_type == "integer":
            scalar["enum"] = [int(choice) for choice in argument.choices]
        elif argument.value_type == "number":
            scalar["enum"] = [float(choice) for choice in argument.choices]
        else:
            scalar["enum"] = list(argument.choices)

    if argument.nargs is None:
        occurrence: dict[str, Any] = scalar
    elif argument.nargs == "?":
        occurrence = {"anyOf": [scalar, {"type": "null"}]}
    else:
        occurrence = {"type": "array", "items": scalar}
        if argument.nargs in ("+", "parser"):
            occurrence["minItems"] = 1
        elif isinstance(argument.nargs, int):
            occurrence["minItems"] = argument.nargs
            occurrence["maxItems"] = argument.nargs

    schema: dict[str, Any]
    match argument.action:
        case ActionKind.STORE:
            schema = occurrence
        case ActionKind.APPEND:
            schema = {"type": "array", "items": occurrence}
            if argument.required:
                schema["minItems"] = 1
        case ActionKind.EXTEND:
            if argument.nargs is None:
                schema = {"type": "array", "items": scalar}
                if argument.required:
                    schema["minItems"] = 1
            elif argument.nargs == "?":
                schema = {"type": "array", "items": occurrence}
                if argument.required:
                    schema["minItems"] = 1
            else:
                schema = occurrence
        case ActionKind.STORE_TRUE | ActionKind.STORE_CONST:
            schema = {"type": "boolean"}
            if argument.required:
                schema["const"] = True
        case ActionKind.STORE_FALSE:
            schema = {"type": "boolean"}
            if argument.required:
                schema["const"] = False
        case ActionKind.BOOLEAN:
            schema = {"type": "boolean"}
        case ActionKind.APPEND_CONST | ActionKind.COUNT:
            schema = {"type": "integer", "minimum": 1 if argument.required else 0}
        case ActionKind.EXTEND_CONST:
            schema = {"type": "array", "items": scalar}

    result: dict[str, Any] = dict(schema)
    if argument.help:
        result["description"] = argument.help
    return result


def argument_argv(argument: Argument, value: Any) -> tuple[str, ...]:
    """Compile one schema-validated argument value into canonical argv tokens."""
    flag = next(
        (candidate for candidate in argument.flags if candidate.startswith("--")),
        argument.flags[0] if argument.flags else None,
    )

    match argument.action:
        case ActionKind.STORE:
            prefix = (flag,) if flag else ()
            if argument.nargs == "?" and value is None:
                return prefix
            if argument.nargs is None:
                return (*prefix, str(value))
            return (*prefix, *(str(item) for item in value))
        case ActionKind.APPEND:
            tokens: list[str] = []
            for occurrence in value:
                if flag:
                    tokens.append(flag)
                if argument.nargs == "?" and occurrence is None:
                    continue
                if argument.nargs is None:
                    tokens.append(str(occurrence))
                else:
                    tokens.extend(str(item) for item in occurrence)
            return tuple(tokens)
        case ActionKind.EXTEND:
            tokens = []
            if argument.nargs in (None, "?"):
                for item in value:
                    if flag:
                        tokens.append(flag)
                    if item is not None:
                        tokens.append(str(item))
                return tuple(tokens)
            if flag:
                tokens.append(flag)
            tokens.extend(str(item) for item in value)
            return tuple(tokens)
        case ActionKind.STORE_TRUE | ActionKind.STORE_CONST:
            if value:
                if flag is None:
                    raise ValueError(f"{argument.id} requires an option flag")
                return (flag,)
            return ()
        case ActionKind.STORE_FALSE:
            if not value:
                if flag is None:
                    raise ValueError(f"{argument.id} requires an option flag")
                return (flag,)
            return ()
        case ActionKind.BOOLEAN:
            positive = next(
                (
                    candidate
                    for candidate in argument.flags
                    if candidate.startswith("--") and not candidate.startswith("--no-")
                ),
                next(
                    (
                        candidate
                        for candidate in argument.flags
                        if not candidate.startswith("--no-")
                    ),
                    None,
                ),
            )
            negative = next(
                (
                    candidate
                    for candidate in argument.flags
                    if candidate.startswith("--no-")
                ),
                None,
            )
            selected = positive if value else negative
            if selected is None:
                raise ValueError(f"{argument.id} lacks a flag for {value=}")
            return (selected,)
        case ActionKind.APPEND_CONST | ActionKind.COUNT:
            if flag is None:
                raise ValueError(f"{argument.id} requires an option flag")
            return (flag,) * value
        case ActionKind.EXTEND_CONST:
            if flag is None:
                raise ValueError(f"{argument.id} requires an option flag")
            return (flag, *(str(item) for item in value))


def argument_active_schema(
    argument: Argument,
    argument_id: str,
) -> dict[str, Any]:
    """Describe when a structured value emits this argparse action."""
    condition: dict[str, Any] = {"required": [argument_id]}
    match argument.action:
        case ActionKind.STORE_TRUE | ActionKind.STORE_CONST:
            condition["properties"] = {argument_id: {"const": True}}
        case ActionKind.STORE_FALSE:
            condition["properties"] = {argument_id: {"const": False}}
        case ActionKind.APPEND_CONST | ActionKind.COUNT:
            condition["properties"] = {argument_id: {"minimum": 1}}
        case ActionKind.APPEND:
            condition["properties"] = {argument_id: {"minItems": 1}}
        case ActionKind.EXTEND if argument.nargs in (None, "?"):
            condition["properties"] = {argument_id: {"minItems": 1}}
    return condition


@dataclass(frozen=True, slots=True)
class CommandTool:
    """One canonical terminal command exposed as a generated MCP tool."""

    commands: tuple[Command, ...]
    disambiguate_name: bool = False
    argument_ids: tuple[tuple[str | None, ...], ...] = field(init=False)
    passthrough_id: str | None = field(init=False)

    def __post_init__(self) -> None:
        if not self.commands:
            raise ValueError("a command tool requires a root-to-terminal branch")
        if not self.commands[-1].terminal:
            raise ValueError("only terminal commands can become generated tools")
        if any(command.raw_only for command in self.commands):
            raise ValueError("raw-only commands cannot become generated tools")
        if (
            any(command.name is None for command in self.commands[1:])
            or self.commands[-1].name is None
        ):
            raise ValueError("a command branch contains an unknown command name")

        used: set[str] = set()
        scoped_ids: list[tuple[str | None, ...]] = []
        for command in self.commands:
            command_ids: list[str | None] = []
            for argument in command.arguments:
                if argument.hidden:
                    command_ids.append(None)
                    continue
                candidate = argument.id
                suffix = 2
                while candidate in used:
                    candidate = f"{argument.id}_{suffix}"
                    suffix += 1
                used.add(candidate)
                command_ids.append(candidate)
            scoped_ids.append(tuple(command_ids))

        passthrough_id: str | None = None
        if self.commands[-1].passthrough:
            passthrough_id = PASSTHROUGH_ARGUMENT
            suffix = 2
            while passthrough_id in used:
                passthrough_id = f"{PASSTHROUGH_ARGUMENT}_{suffix}"
                suffix += 1

        object.__setattr__(self, "argument_ids", tuple(scoped_ids))
        object.__setattr__(self, "passthrough_id", passthrough_id)

    @property
    def path(self) -> tuple[str, ...]:
        """Return the canonical subcommand path without the program name."""
        return tuple(
            command.name for command in self.commands if command.name is not None
        )

    @property
    def name(self) -> str:
        """Return the deterministic MCP tool name."""
        return canonical_tool_name(self.path, disambiguate=self.disambiguate_name)

    @property
    def accepts_opaque_arguments(self) -> bool:
        """Return whether this tool accepts an unparsed argv remainder."""
        return self.passthrough_id is not None or any(
            argument.nargs in {"parser", "remainder"}
            for command in self.commands
            for argument in command.arguments
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        """Return the complete JSON input schema for this command branch."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        constraints: list[dict[str, Any]] = []

        for command, scoped_ids in zip(self.commands, self.argument_ids, strict=True):
            local_arguments: dict[str, tuple[Argument, str]] = {}
            for argument, argument_id in zip(
                command.arguments, scoped_ids, strict=True
            ):
                if argument_id is None:
                    continue
                properties[argument_id] = argument_input_schema(argument)
                local_arguments[argument.id] = (argument, argument_id)
                if argument.required:
                    required.append(argument_id)

            for group in command.exclusive_groups:
                members = [
                    argument_active_schema(*local_arguments[member])
                    for member in group.members
                    if member in local_arguments
                ]
                pairs = [
                    {"allOf": [left, right]}
                    for index, left in enumerate(members)
                    for right in members[index + 1 :]
                ]
                if pairs:
                    constraints.append({"not": {"anyOf": pairs}})
                if group.required:
                    constraints.append({"anyOf": members})

        if self.passthrough_id is not None:
            properties[self.passthrough_id] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Arguments passed unchanged to the plugin command.",
            }

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        if constraints:
            schema["allOf"] = constraints
        Draft202012Validator.check_schema(schema)
        return schema

    def as_mcp_tool(
        self,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> Tool:
        """Create the MCP Tool declaration for this generated command."""
        aliases = [
            {"command": command.name, "aliases": list(command.aliases)}
            for command in self.commands
            if command.name is not None and command.aliases
        ]
        return Tool(
            name=self.name,
            title=f"conda {' '.join(self.path)}",
            description=self.commands[-1].summary
            or f"Run conda {' '.join(self.path)}.",
            input_schema=self.input_schema,
            output_schema=output_schema,
            _meta={
                "conda-cli-mcp/path": list(self.path),
                "conda-cli-mcp/aliases": aliases,
            },
        )

    def compile(self, arguments: Mapping[str, Any]) -> tuple[str, ...]:
        """Validate structured arguments and compile the canonical conda argv."""
        values = dict(arguments)
        Draft202012Validator(self.input_schema).validate(values)

        argv: list[str] = []
        for command, scoped_ids in zip(self.commands, self.argument_ids, strict=True):
            if command.name is not None:
                argv.append(command.name)
            for argument, argument_id in zip(
                command.arguments, scoped_ids, strict=True
            ):
                if argument_id is not None and argument_id in values:
                    argv.extend(argument_argv(argument, values[argument_id]))

        if self.passthrough_id is not None:
            argv.extend(values.get(self.passthrough_id, ()))
        return tuple(argv)


def command_tools(program: Program) -> tuple[CommandTool, ...]:
    """Create generated tools for supported canonical terminal commands."""
    if program.root is None:
        return ()

    diagnostics = tuple(diagnostic.path for diagnostic in program.diagnostics)
    tools: list[CommandTool] = []

    def visit(command: Command, branch: tuple[Command, ...]) -> None:
        current = (*branch, command)
        path = tuple(node.name for node in current if node.name is not None)
        affected = any(
            path[: len(diagnostic)] == diagnostic for diagnostic in diagnostics
        )
        blocked = affected or any(node.raw_only for node in current)
        unknown = any(node.name is None for node in current[1:])

        if path and command.terminal and not blocked and not unknown:
            tools.append(CommandTool(current))
        for child in command.children:
            visit(child, current)

    visit(program.root, ())

    name_counts: dict[str, int] = {}
    for tool in tools:
        name_counts[tool.name] = name_counts.get(tool.name, 0) + 1
    tools = [
        replace(tool, disambiguate_name=True) if name_counts[tool.name] > 1 else tool
        for tool in tools
    ]

    return tuple(tools)
