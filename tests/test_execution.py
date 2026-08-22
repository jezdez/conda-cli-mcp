from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from conda_cli_mcp.execution import CondaExecutor

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.anyio
async def test_execute_preserves_json_and_argv(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda

    result = await executor.execute(
        [str(script), "json", "--value", "two words", "$(echo unsafe)"],
    )

    assert result.exit_code == 0
    assert result.parsed_json == {
        "argv": ["--value", "two words", "$(echo unsafe)"],
    }


@pytest.mark.anyio
async def test_execute_preserves_streams_and_exit_code(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda

    result = await executor.execute([str(script), "streams"])

    assert result.exit_code == 7
    assert result.stdout == "stdout-value\n"
    assert result.stderr == "stderr-value\n"
    assert result.parsed_json is None


@pytest.mark.anyio
async def test_execute_supports_cwd_and_stdin(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda

    cwd_result = await executor.execute([str(script), "cwd"], cwd=tmp_path)
    stdin_result = await executor.execute([str(script), "stdin"], stdin="hello")

    assert cwd_result.stdout.strip() == str(tmp_path)
    assert stdin_result.stdout == "hello\n"


@pytest.mark.anyio
async def test_execute_times_out(fake_conda: tuple[CondaExecutor, Path]) -> None:
    executor, script = fake_conda

    result = await executor.execute(
        [str(script), "sleep", "1"],
        timeout_seconds=0.01,
    )

    assert result.timed_out
    assert result.exit_code is None


@pytest.mark.parametrize("timeout", [0, -1])
def test_executor_rejects_invalid_timeout(tmp_path: Path, timeout: float) -> None:
    executable = tmp_path / "conda"
    executable.touch()

    with pytest.raises(ValueError, match="greater than zero"):
        CondaExecutor(executable, timeout_seconds=timeout)
