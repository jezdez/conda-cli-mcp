from __future__ import annotations

import argparse
import json
import sys
from dataclasses import FrozenInstanceError
from types import ModuleType

import pytest

from conda_cli_mcp.discovery import inspect_parser, main
from conda_cli_mcp.models import ActionKind, Diagnostic, Program


class LazyChoicesAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)


class ExtendConstAction(argparse.Action):
    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        **kwargs: object,
    ) -> None:
        super().__init__(option_strings, dest, nargs="*", **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)


class UnsupportedAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)


def test_inspect_parser_discovers_nested_commands_aliases_and_groups() -> None:
    parser = argparse.ArgumentParser(prog="conda", description="root command")
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser(
        "create",
        aliases=("make",),
        description="create an environment",
    )
    create.add_argument("packages", nargs="+")
    create.add_argument("-c", "--channel", action="append")
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("--secret", help=argparse.SUPPRESS)
    target = create.add_mutually_exclusive_group(required=True)
    target.add_argument("--name")
    target.add_argument("--prefix")
    modes = create.add_subparsers(dest="mode")
    modes.add_parser("from-file", aliases=("file",))

    catalog = inspect_parser(parser, conda_version="26.7.0")

    assert catalog.prog == "conda"
    assert catalog.conda_version == "26.7.0"
    assert catalog.root is not None
    assert catalog.root.summary == "root command"
    assert not catalog.root.terminal
    assert not catalog.diagnostics
    command = catalog.root.children[0]
    assert command.name == "create"
    assert command.aliases == ("make",)
    assert command.summary == "create an environment"
    assert command.terminal
    assert command.children[0].name == "from-file"
    assert command.children[0].aliases == ("file",)
    assert command.children[0].terminal
    assert command.exclusive_groups[0].members == ("name", "prefix")
    assert command.exclusive_groups[0].required

    arguments = {argument.id: argument for argument in command.arguments}
    assert arguments["packages"].nargs == "+"
    assert arguments["channel"].action is ActionKind.APPEND
    assert arguments["dry_run"].action is ActionKind.STORE_TRUE
    assert arguments["secret"].hidden
    assert arguments["secret"].help is None

    assert Program.from_json(catalog.to_json()) == catalog
    assert not hasattr(catalog, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(catalog, "conda_version", "changed")


def test_terminal_tracks_required_and_optional_subparsers() -> None:
    parser = argparse.ArgumentParser(prog="conda")
    subcommands = parser.add_subparsers(dest="command", required=True)
    required = subcommands.add_parser("required")
    required_modes = required.add_subparsers(dest="mode", required=True)
    required_modes.add_parser("leaf")
    optional = subcommands.add_parser("optional")
    optional_modes = optional.add_subparsers(dest="mode")
    optional_modes.add_parser("leaf")

    catalog = inspect_parser(parser)

    assert catalog.root is not None
    assert not catalog.root.terminal
    discovered = {command.name: command for command in catalog.root.children}
    assert not discovered["required"].terminal
    assert discovered["required"].children[0].terminal
    assert discovered["optional"].terminal
    assert discovered["optional"].children[0].terminal


def test_inspect_parser_maps_supported_actions_nargs_choices_and_types() -> None:
    parser = argparse.ArgumentParser(prog="conda-actions", add_help=False)
    parser.add_argument("--store")
    parser.add_argument("--append", action="append")
    parser.add_argument("--extend", action="extend", nargs="+")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--disabled", action="store_false")
    parser.add_argument("--feature", action=argparse.BooleanOptionalAction)
    parser.add_argument("--constant", action="store_const", const="value")
    parser.add_argument("--tag", action="append_const", const="value")
    parser.add_argument("--verbose", action="count")
    parser.add_argument("--tempfiles", action=ExtendConstAction)
    parser.add_argument(
        "--lazy-choice",
        action=LazyChoicesAction,
        choices=("one", "two"),
    )
    parser.add_argument("--integer", type=int)
    parser.add_argument("--number", type=float)
    parser.add_argument("--fixed", nargs=2)
    parser.add_argument("--optional", nargs="?")
    parser.add_argument("--many", nargs="*")
    parser.add_argument("--some", nargs="+")
    parser.add_argument("remainder", nargs=argparse.REMAINDER)
    parser.add_argument("parser_args", nargs=argparse.PARSER)

    catalog = inspect_parser(parser)

    assert catalog.root is not None
    arguments = {argument.id: argument for argument in catalog.root.arguments}
    expected_actions = {
        "store": ActionKind.STORE,
        "append": ActionKind.APPEND,
        "extend": ActionKind.EXTEND,
        "enabled": ActionKind.STORE_TRUE,
        "disabled": ActionKind.STORE_FALSE,
        "feature": ActionKind.BOOLEAN,
        "constant": ActionKind.STORE_CONST,
        "tag": ActionKind.APPEND_CONST,
        "verbose": ActionKind.COUNT,
        "tempfiles": ActionKind.EXTEND_CONST,
        "lazy_choice": ActionKind.STORE,
    }
    assert {
        argument_id: arguments[argument_id].action for argument_id in expected_actions
    } == expected_actions
    assert arguments["feature"].flags == ("--feature", "--no-feature")
    assert arguments["lazy_choice"].choices == ("one", "two")
    assert arguments["integer"].value_type == "integer"
    assert arguments["number"].value_type == "number"
    assert arguments["fixed"].nargs == 2
    assert arguments["optional"].nargs == "?"
    assert arguments["many"].nargs == "*"
    assert arguments["some"].nargs == "+"
    assert arguments["remainder"].nargs == "remainder"
    assert arguments["parser_args"].nargs == "parser"


def test_discovery_limits_raw_only_to_affected_visible_commands() -> None:
    parser = argparse.ArgumentParser(prog="conda")
    subcommands = parser.add_subparsers(dest="command")
    good = subcommands.add_parser("good")
    good.add_argument("--known")
    hidden = subcommands.add_parser("hidden")
    hidden.add_argument(
        "--internal",
        action=UnsupportedAction,
        help=argparse.SUPPRESS,
    )
    bad = subcommands.add_parser("bad")
    bad.add_argument("--unknown", action=UnsupportedAction)
    bad_nargs = bad.add_argument("--bad-nargs", action=LazyChoicesAction)
    bad_nargs.nargs = "unsupported"

    catalog = inspect_parser(parser)

    assert catalog.root is not None
    assert not catalog.root.raw_only
    discovered = {command.name: command for command in catalog.root.children}
    assert not discovered["good"].raw_only
    assert not discovered["hidden"].raw_only
    assert not discovered["hidden"].arguments
    assert discovered["bad"].raw_only
    assert not discovered["bad"].arguments
    assert len(catalog.diagnostics) == 2
    assert {diagnostic.path for diagnostic in catalog.diagnostics} == {("bad",)}
    assert any(
        diagnostic.reason == "unsupported argparse action"
        for diagnostic in catalog.diagnostics
    )
    assert any(
        "unsupported nargs" in diagnostic.reason for diagnostic in catalog.diagnostics
    )


def test_discovery_marks_greedy_plugin_commands_as_passthrough() -> None:
    parser = argparse.ArgumentParser(prog="conda")
    subcommands = parser.add_subparsers(dest="command")
    plugin = subcommands.add_parser("plugin", aliases=("extension",))
    plugin.greedy = True

    catalog = inspect_parser(parser)

    assert catalog.root is not None
    command = catalog.root.children[0]
    assert command.name == "plugin"
    assert command.aliases == ("extension",)
    assert command.passthrough
    assert not command.raw_only


def test_program_round_trips_unavailable_discovery() -> None:
    catalog = Program(
        prog="conda",
        conda_version="unknown",
        root=None,
        diagnostics=(
            Diagnostic(path=(), reason="target interpreter exited with status 1"),
        ),
    )

    restored = Program.from_json(catalog.to_json())

    assert restored == catalog
    assert restored.root is None


def test_module_entry_point_prints_catalog_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser(prog="target-conda")
    conda = ModuleType("conda")
    conda.__version__ = "99.1"
    conda_cli = ModuleType("conda.cli")
    conda_argparse = ModuleType("conda.cli.conda_argparse")
    conda_argparse.generate_parser = lambda: parser
    monkeypatch.setitem(sys.modules, "conda", conda)
    monkeypatch.setitem(sys.modules, "conda.cli", conda_cli)
    monkeypatch.setitem(sys.modules, "conda.cli.conda_argparse", conda_argparse)

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["prog"] == "target-conda"
    assert payload["conda_version"] == "99.1"
