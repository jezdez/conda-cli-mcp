from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .command import CommandTool


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    """Safety requirements and MCP hints for one conda operation."""

    path: tuple[str, ...]
    read_only: bool
    open_world: bool
    requires_write: bool = False
    requires_exec: bool = False

    def as_tool_annotations(self) -> ToolAnnotations:
        """Return the MCP annotation representation of this operation."""
        return ToolAnnotations(
            read_only_hint=self.read_only,
            destructive_hint=not self.read_only,
            idempotent_hint=self.read_only,
            open_world_hint=self.open_world,
        )


class PolicyViolation(PermissionError):
    """An operation requires startup enablement absent from the policy."""

    missing_options: tuple[str, ...]

    def __init__(
        self,
        operation: OperationPolicy,
        missing_options: tuple[str, ...],
    ) -> None:
        self.missing_options = missing_options
        target = "conda " + " ".join(operation.path) if operation.path else "conda"
        options = " and ".join(missing_options)
        super().__init__(f"{target} requires {options}")


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    """Immutable startup policy for conda subprocess execution."""

    allow_write: bool = False
    allow_exec: bool = False

    ALIASES: ClassVar[Mapping[str, str]] = MappingProxyType(
        {"check": "doctor", "uninstall": "remove", "upgrade": "update"}
    )
    NESTED_COMMANDS: ClassVar[Mapping[tuple[str, ...], frozenset[str]]] = (
        MappingProxyType(
            {
                ("env",): frozenset(
                    {"config", "create", "export", "list", "remove", "update"}
                ),
                ("env", "config"): frozenset({"vars"}),
                ("env", "config", "vars"): frozenset({"list", "set", "unset"}),
                ("menuinst",): frozenset({"install", "remove"}),
                ("pypi",): frozenset({"convert", "index", "install"}),
                ("repoquery",): frozenset({"depends", "search", "whoneeds"}),
                ("self",): frozenset({"install", "remove", "reset", "update"}),
            }
        )
    )
    OPTIONS_WITH_VALUES: ClassVar[frozenset[str]] = frozenset(
        {
            "-c",
            "--channel",
            "--console",
            "--file",
            "-f",
            "--name",
            "-n",
            "--platform",
            "--prefix",
            "-p",
            "--repodata-fn",
            "--solver",
            "--subdir",
        }
    )
    CONFIG_MUTATIONS: ClassVar[frozenset[str]] = frozenset(
        {
            "--add",
            "--append",
            "--prepend",
            "--remove",
            "--remove-key",
            "--set",
            "--stdin",
            "--write-default",
        }
    )
    MUTATING_OPTIONS: ClassVar[frozenset[str]] = CONFIG_MUTATIONS | frozenset(
        {"-f", "--file", "--fix", "--heal", "-r", "--reset"}
    )
    READ_ONLY_COMMANDS: ClassVar[frozenset[str]] = frozenset(
        {
            "activate",
            "commands",
            "compare",
            "deactivate",
            "export",
            "info",
            "list",
            "notices",
            "repoquery",
            "search",
        }
    )
    NETWORK_READS: ClassVar[frozenset[str]] = frozenset(
        {"notices", "repoquery", "search"}
    )
    MUTATING_COMMANDS: ClassVar[frozenset[str]] = frozenset(
        {
            "clean",
            "content-trust",
            "create",
            "index",
            "init",
            "install",
            "menuinst",
            "package",
            "remove",
            "rename",
            "update",
        }
    )
    NETWORK_MUTATIONS: ClassVar[frozenset[str]] = frozenset(
        {"content-trust", "create", "install", "update"}
    )
    DRY_RUN_PATHS: ClassVar[frozenset[tuple[str, ...]]] = frozenset(
        {
            ("clean",),
            ("create",),
            ("doctor",),
            ("env", "create"),
            ("env", "remove"),
            ("init",),
            ("install",),
            ("pypi", "install"),
            ("remove",),
            ("rename",),
            ("self", "install"),
            ("self", "remove"),
            ("self", "reset"),
            ("self", "update"),
            ("update",),
        }
    )

    @classmethod
    def resolve_command_path(cls, argv: Sequence[str]) -> tuple[str, ...]:
        """Resolve a supported canonical command path from raw conda argv."""
        tokens = tuple(argv)
        position = 0
        while position < len(tokens) and tokens[position].startswith("-"):
            option = tokens[position].split("=", 1)[0]
            position += 1
            if option in cls.OPTIONS_WITH_VALUES and "=" not in tokens[position - 1]:
                position += 1
        if position >= len(tokens):
            return ()

        top_level = cls.ALIASES.get(tokens[position], tokens[position])
        path = (top_level,)
        position += 1
        children = cls.NESTED_COMMANDS.get(path)
        while children is not None and position < len(tokens):
            token = tokens[position]
            if token == "--":
                break
            if token.startswith("-"):
                option = token.split("=", 1)[0]
                position += 1
                if option in cls.OPTIONS_WITH_VALUES and "=" not in token:
                    position += 1
                continue
            if token not in children:
                break
            path = (*path, token)
            position += 1
            children = cls.NESTED_COMMANDS.get(path)
        return path

    def classify(
        self,
        argv: Sequence[str],
        *,
        command: CommandTool | None = None,
        raw: bool = False,
    ) -> OperationPolicy:
        """Classify one compiled invocation for runtime enforcement."""
        tokens = tuple(argv)
        path = (
            command.path if command is not None else self.resolve_command_path(tokens)
        )
        if path:
            path = (self.ALIASES.get(path[0], path[0]), *path[1:])

        option_tokens = tokens[: tokens.index("--")] if "--" in tokens else tokens
        exact_options = {
            token.split("=", 1)[0] for token in option_tokens if token.startswith("-")
        }
        expanded_options = {
            candidate
            for option in exact_options
            for candidate in self.MUTATING_OPTIONS
            if (
                option.startswith("--")
                and candidate.startswith("--")
                and candidate.startswith(option)
            )
            or (
                option.startswith("-")
                and not option.startswith("--")
                and len(candidate) == 2
                and candidate[1] in option[1:]
            )
        }
        option_names = frozenset(exact_options | expanded_options)
        top_level = path[0] if path else None
        read_only = False
        open_world = True
        requires_write = True
        requires_exec = raw or (
            command is not None and command.accepts_opaque_arguments
        )

        if top_level in self.READ_ONLY_COMMANDS:
            read_only = True
            open_world = top_level in self.NETWORK_READS
            requires_write = False
            if top_level == "export" and option_names & {"-f", "--file"}:
                read_only = False
                requires_write = True
        elif top_level == "config":
            requires_write = bool(option_names & self.CONFIG_MUTATIONS)
            read_only = not requires_write
            open_world = False
        elif top_level == "doctor":
            requires_write = bool(option_names & {"--fix", "--heal"})
            read_only = not requires_write
            open_world = False
        elif top_level == "env":
            if path in {
                ("env",),
                ("env", "config"),
                ("env", "config", "vars"),
                ("env", "config", "vars", "list"),
                ("env", "export"),
                ("env", "list"),
            }:
                read_only = True
                open_world = False
                requires_write = False
                if path == ("env", "export") and option_names & {"-f", "--file"}:
                    read_only = False
                    requires_write = True
            elif path in {
                ("env", "config", "vars", "set"),
                ("env", "config", "vars", "unset"),
                ("env", "create"),
                ("env", "remove"),
                ("env", "update"),
            }:
                open_world = path in {("env", "create"), ("env", "update")}
        elif top_level == "run":
            requires_write = False
            requires_exec = True
        elif top_level == "package":
            open_world = False
            if option_names & {
                "-u",
                "-w",
                "--untracked",
                "--which",
            } and not option_names & {"-r", "--reset"}:
                read_only = True
                requires_write = False
        elif top_level in self.MUTATING_COMMANDS:
            open_world = top_level in self.NETWORK_MUTATIONS
        elif top_level == "pypi":
            open_world = path == ("pypi", "install")
        elif top_level == "self":
            open_world = True

        dry_run = path in self.DRY_RUN_PATHS and bool(
            option_names & {"-d", "--dry-run"}
        )
        if dry_run:
            read_only = True
            requires_write = False

        return OperationPolicy(
            path=path,
            read_only=read_only,
            open_world=open_world,
            requires_write=requires_write,
            requires_exec=requires_exec,
        )

    def describe(
        self,
        command: CommandTool | None = None,
        *,
        raw: bool = False,
    ) -> OperationPolicy:
        """Describe the broadest behavior exposed by one MCP tool."""
        if raw:
            return OperationPolicy(
                path=(),
                read_only=False,
                open_world=True,
                requires_write=True,
                requires_exec=True,
            )
        if command is None:
            raise ValueError("generated tool metadata is required")

        operation = self.classify(command.path, command=command)
        if operation.path in {
            ("config",),
            ("doctor",),
            ("env", "export"),
            ("export",),
        }:
            return OperationPolicy(
                path=operation.path,
                read_only=False,
                open_world=operation.open_world,
                requires_write=True,
                requires_exec=operation.requires_exec,
            )
        return operation

    def enforce(
        self,
        argv: Sequence[str],
        *,
        command: CommandTool | None = None,
        raw: bool = False,
    ) -> OperationPolicy:
        """Return the classification or reject missing startup enablement."""
        operation = self.classify(argv, command=command, raw=raw)
        missing_options = tuple(
            option
            for required, enabled, option in (
                (operation.requires_write, self.allow_write, "--allow-write"),
                (operation.requires_exec, self.allow_exec, "--allow-exec"),
            )
            if required and not enabled
        )
        if missing_options:
            raise PolicyViolation(operation, missing_options)
        return operation
