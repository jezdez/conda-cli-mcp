from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest
from jsonschema import ValidationError

from conda_cli_mcp.command import (
    CommandTool,
    argument_argv,
    argument_input_schema,
    canonical_tool_name,
    command_tools,
)
from conda_cli_mcp.models import (
    ActionKind,
    Argument,
    Command,
    Diagnostic,
    ExclusiveGroup,
    Program,
)

if TYPE_CHECKING:
    from typing import Any


def make_argument(
    action: ActionKind,
    *,
    argument_id: str = "value",
    flags: tuple[str, ...] = ("-v", "--value"),
    nargs: int | str | None = None,
    value_type: str = "string",
    required: bool = False,
    choices: tuple[str, ...] = (),
    help_text: str | None = None,
) -> Argument:
    return Argument(
        id=argument_id,
        dest=argument_id,
        flags=flags,
        action=action,
        nargs=nargs,
        value_type=value_type,
        required=required,
        choices=choices,
        help=help_text,
    )


def make_tool(
    *arguments: Argument,
    groups: tuple[ExclusiveGroup, ...] = (),
    passthrough: bool = False,
) -> CommandTool:
    return CommandTool(
        (
            Command(name=None),
            Command(
                name="example",
                arguments=tuple(arguments),
                exclusive_groups=groups,
                passthrough=passthrough,
            ),
        )
    )


def test_command_tools_build_canonical_leaves_and_preserve_scope() -> None:
    root = Command(
        name=None,
        arguments=(
            make_argument(
                ActionKind.STORE_TRUE,
                argument_id="json",
                flags=("--json",),
            ),
        ),
        children=(
            Command(
                name="env",
                terminal=False,
                aliases=("environment",),
                arguments=(
                    make_argument(
                        ActionKind.STORE,
                        argument_id="prefix",
                        flags=("-p", "--prefix"),
                    ),
                ),
                children=(
                    Command(
                        name="create",
                        aliases=("new",),
                        summary="Create a conda environment.",
                        arguments=(
                            make_argument(
                                ActionKind.STORE,
                                argument_id="name",
                                flags=("-n", "--name"),
                            ),
                        ),
                    ),
                ),
            ),
            Command(name="build", aliases=("bld",), passthrough=True),
            Command(name="raw", raw_only=True, children=(Command(name="child"),)),
            Command(name="broken"),
            Command(name=None),
        ),
    )
    program = Program(
        prog="conda",
        conda_version="26.7.0",
        root=root,
        diagnostics=(Diagnostic(path=("broken",), reason="unsupported action"),),
    )

    tools = command_tools(program)

    assert [tool.name for tool in tools] == ["conda_env_create", "conda_build"]
    env_tool, build_tool = tools
    assert env_tool.compile(
        {"json": True, "prefix": "/tmp/prefix", "name": "demo"}
    ) == (
        "--json",
        "env",
        "--prefix",
        "/tmp/prefix",
        "create",
        "--name",
        "demo",
    )
    assert build_tool.compile({"args": ["--", "recipe", "--variants", "x"]}) == (
        "build",
        "--",
        "recipe",
        "--variants",
        "x",
    )

    output_schema = {"type": "object"}
    declaration = env_tool.as_mcp_tool(output_schema=output_schema)
    assert declaration.title == "conda env create"
    assert declaration.description == "Create a conda environment."
    assert declaration.output_schema == output_schema
    assert declaration.meta == {
        "conda-cli-mcp/path": ["env", "create"],
        "conda-cli-mcp/aliases": [
            {"command": "env", "aliases": ["environment"]},
            {"command": "create", "aliases": ["new"]},
        ],
    }


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        (
            make_argument(
                ActionKind.STORE,
                choices=("main", "test"),
            ),
            {"type": "string", "enum": ["main", "test"]},
        ),
        (
            make_argument(ActionKind.STORE, nargs="+", value_type="integer"),
            {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
            },
        ),
        (
            make_argument(ActionKind.STORE, nargs="parser"),
            {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        ),
        (
            make_argument(ActionKind.STORE, nargs=2, value_type="number"),
            {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
        ),
        (
            make_argument(ActionKind.STORE, nargs="?"),
            {"anyOf": [{"type": "string"}, {"type": "null"}]},
        ),
        (
            make_argument(ActionKind.STORE, flags=()),
            {"type": "string", "pattern": "^(?!-)"},
        ),
        (
            make_argument(ActionKind.APPEND),
            {"type": "array", "items": {"type": "string"}},
        ),
        (
            make_argument(ActionKind.APPEND, nargs=2),
            {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
        ),
        (
            make_argument(ActionKind.EXTEND),
            {"type": "array", "items": {"type": "string"}},
        ),
        (
            make_argument(ActionKind.EXTEND, nargs="+"),
            {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        ),
        (make_argument(ActionKind.STORE_TRUE), {"type": "boolean"}),
        (make_argument(ActionKind.STORE_FALSE), {"type": "boolean"}),
        (make_argument(ActionKind.BOOLEAN), {"type": "boolean"}),
        (make_argument(ActionKind.STORE_CONST), {"type": "boolean"}),
        (
            make_argument(ActionKind.APPEND_CONST),
            {"type": "integer", "minimum": 0},
        ),
        (
            make_argument(ActionKind.EXTEND_CONST),
            {"type": "array", "items": {"type": "string"}},
        ),
        (
            make_argument(ActionKind.COUNT),
            {"type": "integer", "minimum": 0},
        ),
    ],
)
def test_argument_input_schema_covers_supported_actions(
    argument: Argument,
    expected: dict[str, Any],
) -> None:
    assert argument_input_schema(argument) == expected


def test_argument_input_schema_converts_numeric_choices_and_requirements() -> None:
    integer = make_argument(
        ActionKind.STORE,
        value_type="integer",
        choices=("1", "3"),
        required=True,
        help_text="Number of retries.",
    )
    count = make_argument(ActionKind.COUNT, required=True)
    disabled = make_argument(ActionKind.STORE_FALSE, required=True)

    assert argument_input_schema(integer) == {
        "type": "integer",
        "enum": [1, 3],
        "description": "Number of retries.",
    }
    assert argument_input_schema(count) == {"type": "integer", "minimum": 1}
    assert argument_input_schema(disabled) == {
        "type": "boolean",
        "const": False,
    }


@pytest.mark.parametrize(
    ("argument", "value", "expected"),
    [
        (make_argument(ActionKind.STORE), "text", ("--value", "text")),
        (
            make_argument(ActionKind.STORE, flags=()),
            "text",
            ("text",),
        ),
        (
            make_argument(ActionKind.STORE, nargs="+"),
            ["a", "b"],
            ("--value", "a", "b"),
        ),
        (
            make_argument(ActionKind.STORE, nargs="?"),
            None,
            ("--value",),
        ),
        (
            make_argument(ActionKind.APPEND),
            ["a", "b"],
            ("--value", "a", "--value", "b"),
        ),
        (
            make_argument(ActionKind.APPEND, nargs=2),
            [["a", "b"], ["c", "d"]],
            ("--value", "a", "b", "--value", "c", "d"),
        ),
        (
            make_argument(ActionKind.EXTEND),
            ["a", "b"],
            ("--value", "a", "--value", "b"),
        ),
        (
            make_argument(ActionKind.EXTEND, nargs="?"),
            ["a", None],
            ("--value", "a", "--value"),
        ),
        (
            make_argument(ActionKind.EXTEND, nargs="+"),
            ["a", "b"],
            ("--value", "a", "b"),
        ),
        (make_argument(ActionKind.STORE_TRUE), True, ("--value",)),
        (make_argument(ActionKind.STORE_TRUE), False, ()),
        (make_argument(ActionKind.STORE_FALSE), False, ("--value",)),
        (make_argument(ActionKind.STORE_FALSE), True, ()),
        (
            make_argument(
                ActionKind.BOOLEAN,
                flags=("-c", "--color", "--no-color"),
            ),
            True,
            ("--color",),
        ),
        (
            make_argument(
                ActionKind.BOOLEAN,
                flags=("-c", "--color", "--no-color"),
            ),
            False,
            ("--no-color",),
        ),
        (make_argument(ActionKind.STORE_CONST), True, ("--value",)),
        (make_argument(ActionKind.STORE_CONST), False, ()),
        (
            make_argument(ActionKind.APPEND_CONST),
            2,
            ("--value", "--value"),
        ),
        (
            make_argument(ActionKind.EXTEND_CONST),
            ["first", "second"],
            ("--value", "first", "second"),
        ),
        (
            make_argument(ActionKind.COUNT),
            3,
            ("--value", "--value", "--value"),
        ),
    ],
)
def test_argument_argv_covers_supported_actions(
    argument: Argument,
    value: Any,
    expected: tuple[str, ...],
) -> None:
    assert argument_argv(argument, value) == expected


def test_command_tool_validates_required_and_exclusive_arguments() -> None:
    first = make_argument(
        ActionKind.STORE_TRUE,
        argument_id="first",
        flags=("--first",),
    )
    second = make_argument(
        ActionKind.STORE_TRUE,
        argument_id="second",
        flags=("--second",),
    )
    tool = make_tool(
        first,
        second,
        groups=(ExclusiveGroup(("first", "second"), required=True),),
    )

    with pytest.raises(ValidationError):
        tool.compile({})
    with pytest.raises(ValidationError):
        tool.compile({"first": True, "second": True})
    with pytest.raises(ValidationError):
        tool.compile({"first": False, "second": False})

    assert tool.compile({"first": True, "second": False}) == (
        "example",
        "--first",
    )


def test_command_tool_validates_shape_and_scopes_duplicate_ids() -> None:
    root = Command(
        name=None,
        arguments=(
            make_argument(
                ActionKind.COUNT,
                argument_id="verbose",
                flags=("-v", "--verbose"),
            ),
        ),
    )
    leaf = Command(
        name="search",
        arguments=(
            make_argument(
                ActionKind.STORE_TRUE,
                argument_id="verbose",
                flags=("--verbose",),
            ),
        ),
    )
    tool = CommandTool((root, leaf))

    assert set(tool.input_schema["properties"]) == {"verbose", "verbose_2"}
    assert tool.compile({"verbose": 2, "verbose_2": True}) == (
        "--verbose",
        "--verbose",
        "search",
        "--verbose",
    )
    with pytest.raises(ValidationError):
        tool.compile({"unknown": True})
    with pytest.raises(ValidationError):
        tool.compile({"verbose": "twice"})


def test_passthrough_id_is_disambiguated_and_tokens_are_unchanged() -> None:
    tool = make_tool(
        make_argument(ActionKind.STORE, argument_id="args"),
        passthrough=True,
    )

    assert tool.passthrough_id == "args_2"
    assert tool.compile({"args": "configured", "args_2": ["--", "$(not-a-shell)"]}) == (
        "example",
        "--value",
        "configured",
        "--",
        "$(not-a-shell)",
    )


def test_typed_positionals_reject_options_but_remainder_preserves_them() -> None:
    positional = make_tool(make_argument(ActionKind.STORE, flags=()))
    remainder = make_tool(make_argument(ActionKind.STORE, flags=(), nargs="remainder"))

    with pytest.raises(ValidationError):
        positional.compile({"value": "--json"})
    assert remainder.compile({"value": ["python", "-V"]}) == (
        "example",
        "python",
        "-V",
    )


def test_extend_const_emits_one_flag_for_an_empty_value_list() -> None:
    argument = make_argument(ActionKind.EXTEND_CONST, nargs="*")
    tool = make_tool(argument)

    assert tool.input_schema["properties"]["value"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert tool.compile({"value": []}) == ("example", "--value")
    assert tool.compile({"value": ["one", "two"]}) == (
        "example",
        "--value",
        "one",
        "two",
    )


def test_unavailable_program_and_name_collisions_remain_local() -> None:
    unavailable = Program(
        prog="conda",
        conda_version="unknown",
        root=None,
    )
    collision = Program(
        prog="conda",
        conda_version="26.7.0",
        root=Command(
            name=None,
            children=(
                Command(
                    name="foo",
                    terminal=False,
                    children=(Command(name="bar"),),
                ),
                Command(name="foo_bar"),
                Command(name="safe"),
            ),
        ),
    )

    assert command_tools(unavailable) == ()
    generated = command_tools(collision)
    assert len(generated) == 3
    assert generated[-1].name == "conda_safe"
    assert generated[0].name != generated[1].name
    assert all(tool.name.startswith("conda_foo_bar_") for tool in generated[:2])


def test_terminal_nonleaf_commands_and_their_children_receive_tools() -> None:
    program = Program(
        prog="conda",
        conda_version="26.7.0",
        root=Command(
            name=None,
            terminal=False,
            children=(
                Command(
                    name="config",
                    children=(Command(name="sources"),),
                ),
            ),
        ),
    )

    generated = command_tools(program)

    assert [tool.name for tool in generated] == [
        "conda_config",
        "conda_config_sources",
    ]
    assert generated[0].compile({}) == ("config",)
    assert generated[1].compile({}) == ("config", "sources")


def test_command_tool_is_frozen_and_names_are_canonical() -> None:
    tool = make_tool()

    assert canonical_tool_name(("env", "create-from-file")) == (
        "conda_env_create-from-file"
    )
    sanitized = canonical_tool_name(("plugin:name",))
    long_name = canonical_tool_name(("x" * 200,))
    assert sanitized.startswith("conda_plugin_name_")
    assert len(long_name) == 128
    assert long_name == canonical_tool_name(("x" * 200,))
    with pytest.raises(FrozenInstanceError):
        tool.commands = ()
