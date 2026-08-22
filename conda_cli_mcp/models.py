from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from typing import Any

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
NArgs = int | Literal["?", "*", "+", "remainder", "parser"] | None
ValueType = Literal["string", "integer", "number"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Structured outcome of one conda child process."""

    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    parsed_json: JsonValue | None = None
    timed_out: bool = False
    cancelled: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    restart_required: bool = False

    @property
    def failed(self) -> bool:
        return self.exit_code not in (0, None) or self.timed_out or self.cancelled

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the stable MCP structured-output representation."""
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "parsed_json": self.parsed_json,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "restart_required": self.restart_required,
        }

    def summary(self) -> str:
        """Return a concise text result for MCP clients without structured output."""
        if self.timed_out:
            return "conda command timed out"
        if self.cancelled:
            return "conda command was cancelled"
        return f"conda command exited with {self.exit_code}"


class ActionKind(str, Enum):
    """Portable argparse action semantics used by the CLI catalog."""

    STORE = "store"
    APPEND = "append"
    EXTEND = "extend"
    STORE_TRUE = "store_true"
    STORE_FALSE = "store_false"
    BOOLEAN = "boolean"
    STORE_CONST = "store_const"
    APPEND_CONST = "append_const"
    COUNT = "count"
    EXTEND_CONST = "extend_const"


@dataclass(frozen=True, slots=True)
class Argument:
    """One positional or optional argument accepted by a command."""

    id: str
    dest: str
    flags: tuple[str, ...]
    action: ActionKind
    nargs: NArgs
    value_type: ValueType
    required: bool = False
    choices: tuple[str, ...] = ()
    metavar: tuple[str, ...] = ()
    help: str | None = None
    hidden: bool = False

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "id": self.id,
            "dest": self.dest,
            "flags": list(self.flags),
            "action": self.action.value,
            "nargs": self.nargs,
            "value_type": self.value_type,
            "required": self.required,
            "choices": list(self.choices),
            "metavar": list(self.metavar),
            "help": self.help,
            "hidden": self.hidden,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Argument:
        """Restore an argument from its JSON-compatible representation."""
        return cls(
            id=data["id"],
            dest=data["dest"],
            flags=tuple(data["flags"]),
            action=ActionKind(data["action"]),
            nargs=data["nargs"],
            value_type=data["value_type"],
            required=data["required"],
            choices=tuple(data["choices"]),
            metavar=tuple(data["metavar"]),
            help=data["help"],
            hidden=data["hidden"],
        )


@dataclass(frozen=True, slots=True)
class ExclusiveGroup:
    """Arguments where argparse permits at most one member."""

    members: tuple[str, ...]
    required: bool = False

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {"members": list(self.members), "required": self.required}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExclusiveGroup:
        """Restore a mutually exclusive group from JSON-compatible data."""
        return cls(
            members=tuple(data["members"]),
            required=data["required"],
        )


@dataclass(frozen=True, slots=True)
class Command:
    """One command node in the discovered conda CLI tree."""

    name: str | None
    aliases: tuple[str, ...] = ()
    summary: str | None = None
    arguments: tuple[Argument, ...] = ()
    exclusive_groups: tuple[ExclusiveGroup, ...] = ()
    children: tuple[Command, ...] = ()
    terminal: bool = True
    passthrough: bool = False
    raw_only: bool = False

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "summary": self.summary,
            "arguments": [argument.as_dict() for argument in self.arguments],
            "exclusive_groups": [group.as_dict() for group in self.exclusive_groups],
            "children": [child.as_dict() for child in self.children],
            "terminal": self.terminal,
            "passthrough": self.passthrough,
            "raw_only": self.raw_only,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Command:
        """Restore a command tree from JSON-compatible data."""
        return cls(
            name=data["name"],
            aliases=tuple(data["aliases"]),
            summary=data["summary"],
            arguments=tuple(Argument.from_dict(item) for item in data["arguments"]),
            exclusive_groups=tuple(
                ExclusiveGroup.from_dict(item) for item in data["exclusive_groups"]
            ),
            children=tuple(Command.from_dict(item) for item in data["children"]),
            terminal=data["terminal"],
            passthrough=data["passthrough"],
            raw_only=data["raw_only"],
        )


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A discovery problem that prevents typed exposure of one command."""

    path: tuple[str, ...]
    reason: str
    action_type: str | None = None

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "path": list(self.path),
            "reason": self.reason,
            "action_type": self.action_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Diagnostic:
        """Restore a diagnostic from JSON-compatible data."""
        return cls(
            path=tuple(data["path"]),
            reason=data["reason"],
            action_type=data["action_type"],
        )


@dataclass(frozen=True, slots=True)
class Program:
    """The immutable CLI catalog discovered in a target conda environment."""

    prog: str
    conda_version: str
    root: Command | None
    diagnostics: tuple[Diagnostic, ...] = ()

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "prog": self.prog,
            "conda_version": self.conda_version,
            "root": self.root.as_dict() if self.root is not None else None,
            "diagnostics": [diagnostic.as_dict() for diagnostic in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Program:
        """Restore a catalog from JSON-compatible data."""
        root = data["root"]
        return cls(
            prog=data["prog"],
            conda_version=data["conda_version"],
            root=Command.from_dict(root) if root is not None else None,
            diagnostics=tuple(
                Diagnostic.from_dict(item) for item in data["diagnostics"]
            ),
        )

    def to_json(self) -> str:
        """Serialize the complete catalog as deterministic JSON."""
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> Program:
        """Restore a complete catalog from JSON."""
        return cls.from_dict(json.loads(payload))
