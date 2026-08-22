from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from mcp import Client, MCPError

from conda_cli_mcp.models import (
    ActionKind,
    Argument,
    Command,
    ExecutionResult,
    Program,
)
from conda_cli_mcp.server import EXECUTE_TOOL_NAME, CondaMCPServer

if TYPE_CHECKING:
    from pathlib import Path

    from conda_cli_mcp.execution import CondaExecutor


@dataclass
class RecordingExecutor:
    calls: list[tuple[str, ...]] = field(default_factory=list)

    async def execute(
        self,
        argv: list[str] | tuple[str, ...],
        **_options: object,
    ) -> ExecutionResult:
        self.calls.append(tuple(argv))
        return ExecutionResult(
            exit_code=0,
            stdout='{"ok": true}\n',
            stderr="",
            duration_ms=1,
            parsed_json={"ok": True},
        )


@pytest.mark.anyio
async def test_execute_tool_returns_structured_result(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    server = CondaMCPServer(executor)

    result = await server.execute({"argv": [str(script), "json", "value"]})

    assert not result.is_error
    assert result.structured_content["parsed_json"] == {"argv": ["value"]}
    assert server.execute_tool.name == EXECUTE_TOOL_NAME


@pytest.mark.anyio
async def test_execute_tool_validates_arguments(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, _script = fake_conda
    server = CondaMCPServer(executor)

    with pytest.raises(MCPError):
        await server.execute({"argv": "info"})


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
    server = CondaMCPServer(executor, program)  # type: ignore[arg-type]

    async with Client(server.server) as client:
        listed = await client.list_tools()
        result = await client.call_tool("conda_info", {"verbose": 2})

    assert [tool.name for tool in listed.tools] == ["conda_execute", "conda_info"]
    assert listed.tools[1].output_schema is not None
    assert executor.calls == [("--verbose", "--verbose", "info")]
    assert result.structured_content["parsed_json"] == {"ok": True}
