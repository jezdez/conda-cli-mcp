from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp import MCPError

from conda_cli_mcp.server import EXECUTE_TOOL_NAME, CondaMCPServer

if TYPE_CHECKING:
    from pathlib import Path

    from conda_cli_mcp.execution import CondaExecutor


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
