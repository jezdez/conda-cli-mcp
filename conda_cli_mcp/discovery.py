from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING

from .models import (
    ActionKind,
    Argument,
    Command,
    Diagnostic,
    ExclusiveGroup,
    Program,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import NArgs, ValueType


class _UnsupportedParserFeature(ValueError):
    pass


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
    raise _UnsupportedParserFeature(f"unsupported nargs value {value!r}")


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
            f"could not evaluate choices: {type(error).__name__}: {error}"
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


def main() -> int:
    """Print discovery JSON from the target conda interpreter."""
    from conda import __version__ as conda_version
    from conda.cli.conda_argparse import generate_parser

    program = inspect_parser(generate_parser(), conda_version=conda_version)
    sys.stdout.write(f"{program.to_json()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
