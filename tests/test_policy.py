from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from conda_cli_mcp.command import CommandTool
from conda_cli_mcp.models import ActionKind, Argument, Command
from conda_cli_mcp.policy import PolicyViolation, SafetyPolicy

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def command_tool() -> Callable[[tuple[str, ...], bool], CommandTool]:
    def build(path: tuple[str, ...], passthrough: bool = False) -> CommandTool:
        branch = [Command(name=None, terminal=False)]
        branch.extend(
            Command(
                name=name,
                terminal=index == len(path) - 1,
                passthrough=passthrough and index == len(path) - 1,
            )
            for index, name in enumerate(path)
        )
        return CommandTool(tuple(branch))

    return build


@pytest.mark.parametrize(
    (
        "argv",
        "path",
        "read_only",
        "open_world",
        "requires_write",
        "requires_exec",
    ),
    [
        (("activate", "base"), ("activate",), True, False, False, False),
        (("deactivate",), ("deactivate",), True, False, False, False),
        (("info",), ("info",), True, False, False, False),
        (("search", "python"), ("search",), True, True, False, False),
        (("export",), ("export",), True, False, False, False),
        (
            ("export", "--file", "environment.yml"),
            ("export",),
            False,
            False,
            True,
            False,
        ),
        (("export", "--fi=env.yml"), ("export",), False, False, True, False),
        (("export", "-fenv.yml"), ("export",), False, False, True, False),
        (("config", "--show"), ("config",), True, False, False, False),
        (
            ("config", "--set", "auto_activate_base", "false"),
            ("config",),
            False,
            False,
            True,
            False,
        ),
        (("config", "--stdin"), ("config",), False, False, True, False),
        (("config", "--write-d"), ("config",), False, False, True, False),
        (("doctor", "--list"), ("doctor",), True, False, False, False),
        (("check", "--fix"), ("doctor",), False, False, True, False),
        (("doctor", "--fi"), ("doctor",), False, False, True, False),
        (
            ("doctor", "--fi", "--dry-r"),
            ("doctor",),
            False,
            False,
            True,
            False,
        ),
        (
            ("env", "export", "--file=environment.yml"),
            ("env", "export"),
            False,
            False,
            True,
            False,
        ),
        (
            ("env", "config", "vars", "list"),
            ("env", "config", "vars", "list"),
            True,
            False,
            False,
            False,
        ),
        (
            ("env", "config", "vars", "set", "TOKEN=value"),
            ("env", "config", "vars", "set"),
            False,
            False,
            True,
            False,
        ),
        (
            ("env", "config", "vars", "unset", "TOKEN"),
            ("env", "config", "vars", "unset"),
            False,
            False,
            True,
            False,
        ),
        (
            ("env", "create", "-n", "demo"),
            ("env", "create"),
            False,
            True,
            True,
            False,
        ),
        (("uninstall", "python"), ("remove",), False, False, True, False),
        (("upgrade", "python"), ("update",), False, True, True, False),
        (
            ("install", "--dry-run", "python"),
            ("install",),
            True,
            True,
            False,
            False,
        ),
        (
            ("doctor", "--fix", "--dry-run"),
            ("doctor",),
            True,
            False,
            False,
            False,
        ),
        (
            ("self", "update"),
            ("self", "update"),
            False,
            True,
            True,
            False,
        ),
        (
            ("pypi", "install", "requests"),
            ("pypi", "install"),
            False,
            True,
            True,
            False,
        ),
        (
            ("package", "--which", "bin/python"),
            ("package",),
            True,
            False,
            False,
            False,
        ),
        (
            ("package", "--reset"),
            ("package",),
            False,
            False,
            True,
            False,
        ),
        (
            ("run", "python", "-V"),
            ("run",),
            False,
            True,
            False,
            True,
        ),
        (("greedy",), ("greedy",), False, True, True, True),
    ],
)
def test_classify_invocations(
    command_tool: Callable[[tuple[str, ...], bool], CommandTool],
    argv: tuple[str, ...],
    path: tuple[str, ...],
    read_only: bool,
    open_world: bool,
    requires_write: bool,
    requires_exec: bool,
) -> None:
    tool = command_tool(path, path == ("greedy",))

    operation = SafetyPolicy().classify(argv, command=tool)

    assert operation.path == path
    assert operation.read_only is read_only
    assert operation.open_world is open_world
    assert operation.requires_write is requires_write
    assert operation.requires_exec is requires_exec


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("--no-plugins", "info"), ("info",)),
        (("uninstall", "python"), ("remove",)),
        (("upgrade", "python"), ("update",)),
        (("check", "--fix"), ("doctor",)),
        (
            ("env", "config", "vars", "set", "VALUE=1"),
            ("env", "config", "vars", "set"),
        ),
        (
            ("pypi", "--name", "demo", "install", "requests"),
            ("pypi", "install"),
        ),
        (
            ("repoquery", "--channel=conda-forge", "search", "python"),
            ("repoquery", "search"),
        ),
        (("opaque", "--anything"), ("opaque",)),
        ((), ()),
    ],
)
def test_resolve_command_path(argv: tuple[str, ...], expected: tuple[str, ...]) -> None:
    assert SafetyPolicy.resolve_command_path(argv) == expected


@pytest.mark.parametrize(
    (
        "allow_write",
        "allow_exec",
        "argv",
        "path",
        "raw",
        "allowed",
        "missing_options",
    ),
    [
        (False, False, ("info",), ("info",), False, True, ()),
        (
            False,
            False,
            ("install", "python"),
            ("install",),
            False,
            False,
            ("--allow-write",),
        ),
        (True, False, ("install", "python"), ("install",), False, True, ()),
        (
            False,
            False,
            ("run", "python"),
            ("run",),
            False,
            False,
            ("--allow-exec",),
        ),
        (False, True, ("run", "python"), ("run",), False, True, ()),
        (
            False,
            False,
            ("acme",),
            ("acme",),
            False,
            False,
            ("--allow-write",),
        ),
        (True, False, ("acme",), ("acme",), False, True, ()),
        (
            False,
            False,
            ("greedy",),
            ("greedy",),
            False,
            False,
            ("--allow-write", "--allow-exec"),
        ),
        (
            True,
            False,
            ("greedy",),
            ("greedy",),
            False,
            False,
            ("--allow-exec",),
        ),
        (True, True, ("greedy",), ("greedy",), False, True, ()),
        (
            False,
            False,
            ("info",),
            ("info",),
            True,
            False,
            ("--allow-exec",),
        ),
        (False, True, ("info",), ("info",), True, True, ()),
        (
            False,
            True,
            ("doctor", "--fi"),
            ("doctor",),
            True,
            False,
            ("--allow-write",),
        ),
        (
            False,
            True,
            ("install", "python"),
            ("install",),
            True,
            False,
            ("--allow-write",),
        ),
        (True, True, ("install", "python"), ("install",), True, True, ()),
        (
            False,
            True,
            ("opaque",),
            ("opaque",),
            True,
            False,
            ("--allow-write",),
        ),
        (True, True, ("opaque",), ("opaque",), True, True, ()),
    ],
)
def test_enforce_enablement_matrix(
    command_tool: Callable[[tuple[str, ...], bool], CommandTool],
    allow_write: bool,
    allow_exec: bool,
    argv: tuple[str, ...],
    path: tuple[str, ...],
    raw: bool,
    allowed: bool,
    missing_options: tuple[str, ...],
) -> None:
    policy = SafetyPolicy(allow_write=allow_write, allow_exec=allow_exec)
    tool = None if raw else command_tool(path, path == ("greedy",))

    if allowed:
        assert policy.enforce(argv, command=tool, raw=raw).path == path
    else:
        with pytest.raises(PolicyViolation) as caught:
            policy.enforce(argv, command=tool, raw=raw)
        assert caught.value.missing_options == missing_options


@pytest.mark.parametrize(
    ("path", "passthrough", "read_only", "open_world", "requires_exec"),
    [
        (("info",), False, True, False, False),
        (("search",), False, True, True, False),
        (("export",), False, False, False, False),
        (("config",), False, False, False, False),
        (("doctor",), False, False, False, False),
        (("env", "export"), False, False, False, False),
        (("env", "config", "vars", "list"), False, True, False, False),
        (("env", "config", "vars", "set"), False, False, False, False),
        (("run",), True, False, True, True),
        (("configured-plugin",), False, False, True, False),
        (("greedy-plugin",), True, False, True, True),
    ],
)
def test_describe_generated_tool_annotations(
    command_tool: Callable[[tuple[str, ...], bool], CommandTool],
    path: tuple[str, ...],
    passthrough: bool,
    read_only: bool,
    open_world: bool,
    requires_exec: bool,
) -> None:
    operation = SafetyPolicy().describe(command_tool(path, passthrough))
    annotations = operation.as_tool_annotations()

    assert operation.read_only is read_only
    assert operation.open_world is open_world
    assert operation.requires_exec is requires_exec
    assert annotations.read_only_hint is read_only
    assert annotations.destructive_hint is (not read_only)
    assert annotations.idempotent_hint is read_only
    assert annotations.open_world_hint is open_world


def test_describe_raw_tool() -> None:
    operation = SafetyPolicy().describe(raw=True)
    annotations = operation.as_tool_annotations()

    assert operation.path == ()
    assert operation.read_only is False
    assert operation.open_world is True
    assert operation.requires_write is True
    assert operation.requires_exec is True
    assert annotations.destructive_hint is True
    assert annotations.idempotent_hint is False


@pytest.mark.parametrize("nargs", ["parser", "remainder"])
def test_remainder_arguments_require_process_execution(nargs: str) -> None:
    tool = CommandTool(
        (
            Command(name=None, terminal=False),
            Command(
                name="plugin",
                arguments=(
                    Argument(
                        id="args",
                        dest="args",
                        flags=(),
                        action=ActionKind.STORE,
                        nargs=nargs,  # type: ignore[arg-type]
                        value_type="string",
                    ),
                ),
            ),
        )
    )

    operation = SafetyPolicy(allow_write=True).classify(
        ("plugin", "python", "-c", "pass"),
        command=tool,
    )

    assert tool.accepts_opaque_arguments
    assert operation.requires_exec


def test_policy_is_immutable() -> None:
    policy = SafetyPolicy()

    with pytest.raises(FrozenInstanceError):
        policy.allow_write = True  # type: ignore[misc]
