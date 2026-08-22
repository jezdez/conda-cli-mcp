from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from importlib import import_module, metadata
from typing import TYPE_CHECKING

if __package__:
    from .models import (
        ActionKind,
        Argument,
        Command,
        Diagnostic,
        ExclusiveGroup,
        Plugin,
        Program,
    )
else:
    from models import (  # ty: ignore[unresolved-import]
        ActionKind,
        Argument,
        Command,
        Diagnostic,
        ExclusiveGroup,
        Plugin,
        Program,
    )

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Any

    from .models import JsonValue, NArgs, ValueType


class _UnsupportedParserFeature(ValueError):
    pass


def inspect_plugins() -> tuple[Plugin, ...]:
    """Inspect external conda entry points installed in this interpreter."""
    from conda.plugins.hookspec import CondaSpecs

    hook_names = tuple(
        sorted(
            name
            for name in dir(CondaSpecs)
            if name.startswith("conda_") and callable(getattr(CondaSpecs, name))
        )
    )
    plugins: list[Plugin] = []
    for distribution in metadata.distributions():
        distribution_name = distribution.metadata["Name"]
        if not distribution_name:
            continue
        for entry_point in distribution.entry_points:
            if entry_point.group != "conda":
                continue
            try:
                loaded = entry_point.load()
            except Exception:
                hooks: tuple[str, ...] = ()
            else:
                implemented: list[str] = []
                plugin_name = getattr(loaded, "__name__", None)
                if callable(loaded) and plugin_name in hook_names:
                    implemented.append(plugin_name)
                for hook_name in hook_names:
                    try:
                        implementation = getattr(loaded, hook_name)
                    except (AttributeError, TypeError):
                        continue
                    if callable(implementation):
                        implemented.append(hook_name)
                hooks = tuple(sorted(set(implemented)))
            plugins.append(
                Plugin(
                    distribution=distribution_name,
                    version=distribution.version,
                    entry_point=entry_point.name,
                    value=entry_point.value,
                    hooks=hooks,
                )
            )
    return tuple(
        sorted(
            plugins,
            key=lambda plugin: (
                plugin.distribution.casefold(),
                plugin.entry_point.casefold(),
                plugin.value,
            ),
        )
    )


def inspect_completion_command(
    command_path: Sequence[str],
) -> dict[str, JsonValue]:
    """Read one command from conda-completion through its public target API."""
    requested = tuple(command_path)
    if any(
        not part or part.startswith("-") or any(char.isspace() for char in part)
        for part in requested
    ):
        raise ValueError("invalid_command_path")

    unavailable: dict[str, JsonValue] = {
        "availability": "not_installed",
        "requested_command_path": list(requested),
        "resolved_command_path": None,
        "alias_target": None,
        "command": None,
        "manifest": None,
        "hint": "Install conda-completion in the target conda environment.",
    }
    try:
        completion_exceptions = import_module("conda_completion.exceptions")
        completion_manifest = import_module("conda_completion.manifest")
        completion_paths = import_module("conda_completion.paths")
        completion_plugin = import_module("conda_completion.plugin")
    except ModuleNotFoundError as error:
        if error.name == "conda_completion":
            return unavailable
        return {
            **unavailable,
            "availability": "unavailable",
            "hint": (
                "Repair the conda-completion installation in the target environment."
            ),
        }
    except ImportError:
        return {
            **unavailable,
            "availability": "unavailable",
            "hint": "Use a conda-completion version with the public manifest API.",
        }

    try:
        completion_version: JsonValue = metadata.version("conda-completion")
    except metadata.PackageNotFoundError:
        completion_version = None
    if isinstance(completion_version, str):
        try:
            release = tuple(int(part) for part in completion_version.split(".", 2)[:2])
        except ValueError:
            release = ()
        if release and release < (0, 3):
            return {
                **unavailable,
                "availability": "unavailable",
                "hint": "Use conda-completion 0.3 or newer in the target environment.",
            }

    required_functions = (
        (completion_manifest, "read_manifest"),
        (completion_paths, "manifest_path"),
    )
    if not all(
        callable(getattr(module, name, None)) for module, name in required_functions
    ):
        return {
            **unavailable,
            "availability": "unavailable",
            "hint": "Use conda-completion 0.3 or newer in the target environment.",
        }

    path = completion_paths.manifest_path()
    try:
        manifest = completion_manifest.read_manifest(path)
    except FileNotFoundError:
        return {
            **unavailable,
            "availability": "not_generated",
            "hint": "Run 'conda completion generate' in the target environment.",
        }
    except (completion_exceptions.ManifestError, OSError):
        return {
            **unavailable,
            "availability": "unavailable",
            "hint": "Regenerate completion.msgpack in the target environment.",
        }

    if not all(
        hasattr(manifest, name)
        for name in (
            "aliases",
            "commands",
            "generated_at",
            "plugin_hash",
            "root_options",
            "runtime_sources",
            "version",
        )
    ):
        return {
            **unavailable,
            "availability": "unavailable",
            "hint": "Use conda-completion 0.3 or newer in the target environment.",
        }

    resolved = list(requested)
    alias_target: list[str] | None = None
    if resolved and (alias := manifest.aliases.get(resolved[0])) is not None:
        alias_target = list(alias.target)
        resolved = [*alias_target, *resolved[1:]]

    options = manifest.root_options
    positionals: list[Any] = []
    subcommands = manifest.commands
    exclusive_groups: list[list[str]] = []
    summary = None
    for part in resolved:
        command = subcommands.get(part)
        if command is None:
            raise LookupError("unknown_command")
        summary = command.summary
        options = command.options
        positionals = command.positionals
        subcommands = command.subcommands
        exclusive_groups = command.exclusive_groups

    try:
        current_plugin_hash = completion_plugin.plugin_entry_point_hash()
    except Exception:
        current_plugin_hash = None
    stored_plugin_hash = manifest.plugin_hash or None
    stale = (
        current_plugin_hash != stored_plugin_hash
        if current_plugin_hash is not None and stored_plugin_hash is not None
        else None
    )
    try:
        command_payload: JsonValue = {
            "summary": summary,
            "options": [
                {"name": name, **option.to_dict()} for name, option in options.items()
            ],
            "positionals": [position.to_dict() for position in positionals],
            "subcommands": [
                {"name": name, "summary": command.summary}
                for name, command in subcommands.items()
            ],
            "exclusive_groups": exclusive_groups,
        }
        runtime_sources: JsonValue = {
            name: source.to_dict() for name, source in manifest.runtime_sources.items()
        }
    except (AttributeError, TypeError, ValueError):
        return {
            **unavailable,
            "availability": "unavailable",
            "hint": "Use conda-completion 0.3 or newer in the target environment.",
        }

    return {
        "availability": "available",
        "requested_command_path": list(requested),
        "resolved_command_path": resolved,
        "alias_target": alias_target,
        "command": command_payload,
        "manifest": {
            "version": manifest.version,
            "generated_at": manifest.generated_at,
            "stored_plugin_hash": stored_plugin_hash,
            "current_plugin_hash": current_plugin_hash,
            "stale": stale,
            "conda_completion_version": completion_version,
            "runtime_sources": runtime_sources,
        },
        "hint": None,
    }


def inspect_parser(
    parser: argparse.ArgumentParser,
    conda_version: str = "unknown",
) -> Program:
    """Build an immutable catalog from a fully configured conda parser."""
    diagnostics: list[Diagnostic] = []
    root = _inspect_command(
        parser,
        name=None,
        aliases=(),
        path=(),
        diagnostics=diagnostics,
    )
    return Program(
        prog=parser.prog,
        conda_version=conda_version,
        root=root,
        diagnostics=tuple(diagnostics),
    )


def _inspect_command(
    parser: argparse.ArgumentParser,
    *,
    name: str | None,
    aliases: tuple[str, ...],
    path: tuple[str, ...],
    diagnostics: list[Diagnostic],
) -> Command:
    arguments: list[Argument] = []
    action_ids: dict[argparse.Action, str] = {}
    used_ids: set[str] = set()
    subparsers: list[argparse.Action] = []
    raw_only = False

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers.append(action)
            continue
        if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
            continue
        try:
            argument = _inspect_argument(action, used_ids)
        except _UnsupportedParserFeature as error:
            if action.help == argparse.SUPPRESS:
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    reason=str(error),
                    action_type=_qualified_name(action),
                )
            )
            raw_only = True
            continue
        arguments.append(argument)
        action_ids[action] = argument.id

    exclusive_groups = tuple(
        ExclusiveGroup(
            members=tuple(
                action_ids[action]
                for action in group._group_actions
                if action in action_ids
            ),
            required=group.required,
        )
        for group in parser._mutually_exclusive_groups
        if any(action in action_ids for action in group._group_actions)
    )

    children: list[Command] = []
    for subparser_action in subparsers:
        try:
            child_specs = _subparser_choices(subparser_action)
        except _UnsupportedParserFeature as error:
            diagnostics.append(
                Diagnostic(
                    path=path,
                    reason=str(error),
                    action_type=_qualified_name(subparser_action),
                )
            )
            raw_only = True
            continue
        for child_name, child_aliases, child_parser in child_specs:
            child_path = (*path, child_name)
            children.append(
                _inspect_command(
                    child_parser,
                    name=child_name,
                    aliases=child_aliases,
                    path=child_path,
                    diagnostics=diagnostics,
                )
            )

    description = parser.description
    return Command(
        name=name,
        aliases=aliases,
        summary=str(description) if description is not None else None,
        arguments=tuple(arguments),
        exclusive_groups=exclusive_groups,
        children=tuple(children),
        terminal=not any(action.required for action in subparsers),
        passthrough=bool(getattr(parser, "greedy", False)),
        raw_only=raw_only,
    )


def _inspect_argument(action: argparse.Action, used_ids: set[str]) -> Argument:
    action_kind = _action_kind(action)
    nargs = _normalize_nargs(action.nargs)
    choices = _normalize_choices(action)
    hidden = action.help == argparse.SUPPRESS
    argument_id = _argument_id(action, used_ids)
    used_ids.add(argument_id)
    return Argument(
        id=argument_id,
        dest=action.dest,
        flags=tuple(action.option_strings),
        action=action_kind,
        nargs=nargs,
        value_type=_value_type(action.type),
        required=action.required,
        choices=choices,
        metavar=_metavar(action.metavar),
        help=None if hidden or action.help is None else str(action.help),
        hidden=hidden,
    )


def _action_kind(action: argparse.Action) -> ActionKind:
    class_name = type(action).__name__
    if class_name == "ExtendConstAction":
        return ActionKind.EXTEND_CONST
    if class_name == "LazyChoicesAction":
        return ActionKind.STORE

    mappings = (
        (argparse.BooleanOptionalAction, ActionKind.BOOLEAN),
        (argparse._StoreTrueAction, ActionKind.STORE_TRUE),
        (argparse._StoreFalseAction, ActionKind.STORE_FALSE),
        (argparse._StoreConstAction, ActionKind.STORE_CONST),
        (argparse._AppendConstAction, ActionKind.APPEND_CONST),
        (argparse._CountAction, ActionKind.COUNT),
        (argparse._ExtendAction, ActionKind.EXTEND),
        (argparse._AppendAction, ActionKind.APPEND),
        (argparse._StoreAction, ActionKind.STORE),
    )
    for action_type, kind in mappings:
        if isinstance(action, action_type):
            return kind
    raise _UnsupportedParserFeature("unsupported argparse action")


def _normalize_nargs(value: object) -> NArgs:
    if value == argparse.REMAINDER:
        return "remainder"
    if value == argparse.PARSER:
        return "parser"
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if value == "?":
        return "?"
    if value == "*":
        return "*"
    if value == "+":
        return "+"
    raise _UnsupportedParserFeature("unsupported nargs value")


def _normalize_choices(action: argparse.Action) -> tuple[str, ...]:
    try:
        choices = action.choices
        if choices is None:
            return ()
        values: Iterable[object]
        if isinstance(choices, Mapping):
            values = choices.keys()
        else:
            values = choices
        return tuple(str(choice) for choice in values)
    except Exception as error:
        raise _UnsupportedParserFeature(
            f"could not evaluate choices: {type(error).__name__}"
        ) from error


def _value_type(converter: object) -> ValueType:
    if converter is int:
        return "integer"
    if converter is float:
        return "number"
    return "string"


def _metavar(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    return (str(value),)


def _argument_id(action: argparse.Action, used_ids: set[str]) -> str:
    if action.option_strings:
        preferred = next(
            (option[2:] for option in action.option_strings if option.startswith("--")),
            action.option_strings[0].lstrip("-"),
        )
        base = preferred.replace("-", "_")
    else:
        base = action.dest.replace("-", "_")
    candidate = base or "argument"
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _subparser_choices(
    action: argparse.Action,
) -> tuple[tuple[str, tuple[str, ...], argparse.ArgumentParser], ...]:
    choices = action.choices
    if not isinstance(choices, Mapping):
        raise _UnsupportedParserFeature("subparser choices are not a mapping")

    grouped: dict[int, tuple[argparse.ArgumentParser, list[str]]] = {}
    for choice, child in choices.items():
        if not isinstance(choice, str) or not isinstance(
            child, argparse.ArgumentParser
        ):
            raise _UnsupportedParserFeature("subparser choice has an invalid value")
        identity = id(child)
        if identity not in grouped:
            grouped[identity] = (child, [])
        grouped[identity][1].append(choice)

    return tuple(
        (names[0], tuple(names[1:]), child)
        for child, names in grouped.values()
        if names
    )


def _qualified_name(action: argparse.Action) -> str:
    action_type = type(action)
    return f"{action_type.__module__}.{action_type.__qualname__}"


def main(argv: Sequence[str] | None = None) -> int:
    """Print discovery JSON from the target conda interpreter."""
    worker_parser = argparse.ArgumentParser()
    mode = worker_parser.add_mutually_exclusive_group()
    mode.add_argument("--plugins", action="store_true")
    mode.add_argument("--completion-command")
    options = worker_parser.parse_args(argv)
    if options.plugins:
        payload = [plugin.as_dict() for plugin in inspect_plugins()]
        sys.stdout.write(
            f"{json.dumps(payload, separators=(',', ':'), sort_keys=True)}\n"
        )
        return 0
    if options.completion_command is not None:
        try:
            request = json.loads(options.completion_command)
            command_path = request["command_path"]
            if not isinstance(command_path, list) or not all(
                isinstance(part, str) for part in command_path
            ):
                raise TypeError
            payload = inspect_completion_command(command_path)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            payload = {"error": "invalid_command_path"}
        except LookupError:
            payload = {"error": "unknown_command"}
        sys.stdout.write(
            f"{json.dumps(payload, separators=(',', ':'), sort_keys=True)}\n"
        )
        return 0

    from conda import __version__ as conda_version
    from conda.cli.conda_argparse import generate_parser

    program = inspect_parser(generate_parser(), conda_version=conda_version)
    sys.stdout.write(f"{program.to_json()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
