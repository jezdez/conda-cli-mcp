from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from mcp import Client, MCPError

from conda_cli_mcp.capabilities import Capabilities
from conda_cli_mcp.models import (
    ActionKind,
    Argument,
    Command,
    ExecutionResult,
    Plugin,
    Program,
)
from conda_cli_mcp.policy import SafetyPolicy
from conda_cli_mcp.server import (
    CAPABILITIES_URI,
    COMPLETION_TOOL_NAME,
    EXECUTE_TOOL_NAME,
    CondaMCPServer,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conda_cli_mcp.execution import CondaExecutor

    ServerFactory = Callable[
        ["RecordingExecutor", tuple[Command, ...], SafetyPolicy], CondaMCPServer
    ]


@dataclass
class RecordingExecutor:
    calls: list[tuple[str, ...]] = field(default_factory=list)
    plugins: tuple[Plugin, ...] = ()
    exit_code: int = 0
    plugin_state_calls: int = 0
    completion_calls: list[tuple[str, ...]] = field(default_factory=list)
    timeout_seconds: float = 900

    async def execute(
        self,
        argv: list[str] | tuple[str, ...],
        **_options: object,
    ) -> ExecutionResult:
        self.calls.append(tuple(argv))
        return ExecutionResult(
            exit_code=self.exit_code,
            stdout='{"ok": true}\n',
            stderr="",
            duration_ms=1,
            parsed_json={"ok": True},
        )

    async def discover_plugin_state(self) -> tuple[str, tuple[Plugin, ...]]:
        self.plugin_state_calls += 1
        return "26.7", self.plugins

    async def inspect_completion_command(
        self,
        command_path: list[str] | tuple[str, ...],
    ) -> dict[str, object]:
        self.completion_calls.append(tuple(command_path))
        return {
            "availability": "available",
            "requested_command_path": list(command_path),
            "resolved_command_path": list(command_path),
            "alias_target": None,
            "command": {
                "summary": "List environments",
                "options": [],
                "positionals": [],
                "subcommands": [],
                "exclusive_groups": [],
            },
            "manifest": {
                "version": 1,
                "generated_at": "2026-08-22T12:00:00Z",
                "stored_plugin_hash": "hash",
                "current_plugin_hash": "hash",
                "stale": False,
                "conda_completion_version": "0.3.0",
                "runtime_sources": {},
            },
            "hint": None,
        }


@pytest.fixture
def server_factory() -> ServerFactory:
    def build(
        executor: RecordingExecutor,
        children: tuple[Command, ...],
        policy: SafetyPolicy,
    ) -> CondaMCPServer:
        program = Program(
            prog="conda",
            conda_version="26.7",
            root=Command(name=None, terminal=False, children=children),
        )
        return CondaMCPServer(  # type: ignore[arg-type]
            executor,
            Capabilities("conda", program, ()),
            policy,
        )

    return build


@pytest.mark.anyio
async def test_execute_tool_returns_structured_result(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    server = CondaMCPServer(
        executor,
        policy=SafetyPolicy(allow_write=True, allow_exec=True),
    )

    result = await server.execute({"argv": [str(script), "json", "value"]})

    assert not result.is_error
    assert result.structured_content["parsed_json"] == {"argv": ["value"]}
    assert json.loads(result.content[1].text) == result.structured_content
    assert server.execute_tool.name == EXECUTE_TOOL_NAME
    assert (
        server.execute_tool.input_schema["properties"]["timeout_seconds"]["maximum"]
        == 2
    )


@pytest.mark.anyio
async def test_execute_tool_validates_arguments(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, _script = fake_conda
    server = CondaMCPServer(
        executor,
        policy=SafetyPolicy(allow_write=True, allow_exec=True),
    )

    with pytest.raises(MCPError) as caught:
        await server.execute({"argv": "secret-value"})

    assert "secret-value" not in str(caught.value)


@pytest.mark.anyio
async def test_generated_tool_compiles_and_executes_scoped_argv() -> None:
    executor = RecordingExecutor()
    program = Program(
        prog="conda",
        conda_version="26.7",
        root=Command(
            name=None,
            terminal=False,
            arguments=(
                Argument(
                    id="verbose",
                    dest="verbose",
                    flags=("--verbose",),
                    action=ActionKind.COUNT,
                    nargs=0,
                    value_type="string",
                ),
            ),
            children=(Command(name="info"),),
        ),
    )
    capabilities = Capabilities("conda", program, ())
    server = CondaMCPServer(executor, capabilities)  # type: ignore[arg-type]

    async with Client(server.server) as client:
        listed = await client.list_tools()
        resources = await client.list_resources()
        resource = await client.read_resource(CAPABILITIES_URI)
        result = await client.call_tool("conda_info", {"verbose": 2})

    assert [tool.name for tool in listed.tools] == ["conda_info"]
    assert listed.tools[0].output_schema is not None
    assert listed.tools[0].annotations.read_only_hint is True
    assert [str(item.uri) for item in resources.resources] == [CAPABILITIES_URI]
    assert json.loads(resource.contents[0].text)["generated_tools"] == ["conda_info"]
    assert executor.calls == [("--verbose", "--verbose", "info")]
    assert result.structured_content["parsed_json"] == {"ok": True}


@pytest.mark.anyio
async def test_completion_plugin_adds_read_only_command_metadata_tool() -> None:
    executor = RecordingExecutor()
    program = Program(
        prog="conda",
        conda_version="26.7",
        root=Command(
            name=None,
            terminal=False,
            children=(Command(name="info"),),
        ),
    )
    plugin = Plugin(
        distribution="conda-completion",
        version="0.3.0",
        entry_point="conda-completion",
        value="conda_completion.plugin",
        hooks=("conda_subcommands",),
    )
    server = CondaMCPServer(  # type: ignore[arg-type]
        executor,
        Capabilities("conda", program, (plugin,)),
    )

    async with Client(server.server) as client:
        listed = await client.list_tools()
        result = await client.call_tool(
            COMPLETION_TOOL_NAME,
            {"command_path": ["env", "list"]},
        )

    assert [tool.name for tool in listed.tools] == [
        COMPLETION_TOOL_NAME,
        "conda_info",
    ]
    completion_tool = listed.tools[0]
    assert completion_tool.annotations.read_only_hint is True
    assert completion_tool.annotations.destructive_hint is False
    assert result.structured_content["command"]["summary"] == "List environments"
    assert json.loads(result.content[0].text) == result.structured_content
    assert executor.completion_calls == [("env", "list")]


@pytest.mark.anyio
async def test_policy_controls_tool_visibility_and_execution(
    server_factory: ServerFactory,
) -> None:
    executor = RecordingExecutor()
    server = server_factory(
        executor,
        (
            Command(name="info"),
            Command(name="install"),
            Command(name="run"),
            Command(name="fixture-plugin", passthrough=True),
        ),
        SafetyPolicy(),
    )

    async with Client(server.server) as client:
        listed = await client.list_tools()
        info = await client.call_tool("conda_info", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_install", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_run", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_fixture-plugin", {"args": []})
        with pytest.raises(MCPError):
            await client.call_tool(EXECUTE_TOOL_NAME, {"argv": ["info"]})

    assert [tool.name for tool in listed.tools] == [
        "conda_info",
        "conda_install",
        "conda_run",
        "conda_fixture-plugin",
    ]
    annotations = {tool.name: tool.annotations for tool in listed.tools}
    assert annotations["conda_info"].read_only_hint is True
    assert annotations["conda_install"].destructive_hint is True
    assert annotations["conda_run"].open_world_hint is True
    assert annotations["conda_fixture-plugin"].open_world_hint is True
    assert info.structured_content["restart_required"] is False
    assert executor.calls == [("info",)]


@pytest.mark.anyio
async def test_write_and_exec_enablement_remain_separate(
    server_factory: ServerFactory,
) -> None:
    executor = RecordingExecutor()
    children = (Command(name="install"), Command(name="run"))
    write_server = server_factory(
        executor,
        children,
        SafetyPolicy(allow_write=True),
    )
    exec_server = server_factory(
        executor,
        children,
        SafetyPolicy(allow_exec=True),
    )

    async with Client(write_server.server) as client:
        await client.call_tool("conda_install", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_run", {})
    async with Client(exec_server.server) as client:
        listed = await client.list_tools()
        await client.call_tool("conda_run", {})
        await client.call_tool(EXECUTE_TOOL_NAME, {"argv": ["info"]})
        with pytest.raises(MCPError) as caught:
            await client.call_tool(EXECUTE_TOOL_NAME, {"argv": ["secret-value"]})

    assert listed.tools[0].name == EXECUTE_TOOL_NAME
    assert listed.tools[0].annotations.open_world_hint is True
    assert "secret-value" not in str(caught.value)
    assert executor.calls == [("install",), ("run",), ("info",)]


@pytest.mark.anyio
async def test_successful_mutation_reports_restart_without_changing_tools(
    server_factory: ServerFactory,
) -> None:
    plugin = Plugin(
        distribution="conda-fixture",
        version="1.0",
        entry_point="fixture",
        value="conda_fixture.plugin",
        hooks=("conda_subcommands",),
    )
    executor = RecordingExecutor(plugins=(plugin,))
    server = server_factory(
        executor,
        (Command(name="info"), Command(name="install")),
        SafetyPolicy(allow_write=True),
    )

    async with Client(server.server) as client:
        before = await client.list_tools()
        changed = await client.call_tool("conda_install", {})
        after = await client.list_tools()
        read = await client.call_tool("conda_info", {})

    assert changed.structured_content["restart_required"] is True
    assert "Restart the MCP server" in changed.content[0].text
    assert read.structured_content["restart_required"] is True
    assert [tool.name for tool in before.tools] == [tool.name for tool in after.tools]
    assert executor.plugin_state_calls == 1


@pytest.mark.anyio
async def test_failed_mutation_does_not_request_restart(
    server_factory: ServerFactory,
) -> None:
    executor = RecordingExecutor(exit_code=1)
    server = server_factory(
        executor,
        (Command(name="install"),),
        SafetyPolicy(allow_write=True),
    )

    async with Client(server.server) as client:
        result = await client.call_tool("conda_install", {})

    assert result.is_error
    assert result.structured_content["restart_required"] is False
    assert executor.plugin_state_calls == 0
