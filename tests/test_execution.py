from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest

from conda_cli_mcp.execution import CondaExecutor

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def discovery_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[CondaExecutor, Path]]:
    info_script = tmp_path / "info"
    info_script.write_text(
        """\
import json
import os
import sys
import time

if sys.argv[1:] != ["--json"]:
    raise SystemExit(91)

mode = os.environ.get("FAKE_INFO_MODE", "success")
if mode == "exit":
    raise SystemExit(17)
if mode == "timeout":
    time.sleep(10)
if mode == "invalid_json":
    print("not JSON")
    raise SystemExit(0)
info = {
    "conda_version": "99.1",
    "sys.executable": os.environ["FAKE_TARGET_PYTHON"],
}
if mode == "missing_version":
    del info["conda_version"]
if mode == "missing_interpreter":
    del info["sys.executable"]
print(json.dumps(info))
"""
    )
    raw_script = tmp_path / "raw"
    raw_script.write_text('print("raw-ok")\n')

    target_modules = tmp_path / "target-modules"
    conda_package = target_modules / "conda"
    conda_cli_package = conda_package / "cli"
    conda_cli_package.mkdir(parents=True)
    (conda_package / "__init__.py").write_text(
        """\
import json
import os
import sys
import time

mode = os.environ.get("FAKE_DISCOVERY_MODE", "success")
if mode == "exit":
    raise SystemExit(23)
if mode == "timeout":
    time.sleep(10)
if mode == "invalid_json":
    print("not JSON")
    raise SystemExit(0)
if mode == "invalid_fields":
    print(json.dumps({
        "prog": "",
        "conda_version": "99.1",
        "root": None,
        "diagnostics": [],
    }))
    raise SystemExit(0)
if mode == "version_mismatch":
    print(json.dumps({
        "prog": "target-conda",
        "conda_version": "98.0",
        "root": None,
        "diagnostics": [],
    }))
    raise SystemExit(0)

package_root = os.environ["FAKE_PACKAGE_ROOT"]
target_modules = os.environ["FAKE_TARGET_MODULES"]
python_path = os.environ.get("PYTHONPATH", "").split(os.pathsep)
if python_path[:2] != [package_root, target_modules]:
    raise RuntimeError("package root was not prepended to PYTHONPATH")

main_spec = getattr(sys.modules["__main__"], "__spec__", None)
marker = {
    "module": getattr(main_spec, "name", None),
    "pythonpath": python_path,
}
with open(os.environ["FAKE_TARGET_MARKER"], "w", encoding="utf-8") as stream:
    json.dump(marker, stream)

__version__ = "99.1"
"""
    )
    (conda_cli_package / "__init__.py").write_text("")
    (conda_cli_package / "conda_argparse.py").write_text(
        """\
import argparse


def generate_parser():
    parser = argparse.ArgumentParser(prog="target-conda")
    parser.add_argument("--json", action="store_true")
    commands = parser.add_subparsers(dest="command")
    plugin = commands.add_parser("plugin-command", aliases=("pc",))
    plugin.add_argument("--value")
    return parser
"""
    )

    marker = tmp_path / "target-marker.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(target_modules))
    monkeypatch.setenv("FAKE_PACKAGE_ROOT", str(Path(__file__).resolve().parent.parent))
    monkeypatch.setenv("FAKE_TARGET_MODULES", str(target_modules))
    monkeypatch.setenv("FAKE_TARGET_MARKER", str(marker))
    monkeypatch.setenv("FAKE_TARGET_PYTHON", sys.executable)
    yield CondaExecutor(Path(sys.executable), timeout_seconds=10), marker


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


@pytest.mark.anyio
async def test_discover_uses_target_interpreter_and_package_root(
    discovery_executor: tuple[CondaExecutor, Path],
) -> None:
    executor, marker_path = discovery_executor

    program = await executor.discover()

    assert program.prog == "target-conda"
    assert program.conda_version == "99.1"
    assert program.root is not None
    assert [(child.name, child.aliases) for child in program.root.children] == [
        ("plugin-command", ("pc",))
    ]
    marker = json.loads(marker_path.read_text())
    assert marker["module"] == "conda_cli_mcp.discovery"
    assert marker["pythonpath"][:2] == [
        str(Path(__file__).resolve().parent.parent),
        os.environ["FAKE_TARGET_MODULES"],
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("exit", "conda info exited with status 17"),
        ("timeout", "conda info timed out"),
        ("invalid_json", "conda info did not return a JSON object"),
        (
            "missing_version",
            "conda info field 'conda_version' is missing or invalid",
        ),
        (
            "missing_interpreter",
            "conda info field 'sys.executable' is missing or invalid",
        ),
    ],
)
async def test_discover_returns_unavailable_program_for_info_failure(
    discovery_executor: tuple[CondaExecutor, Path],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    reason: str,
) -> None:
    executor, _marker = discovery_executor
    monkeypatch.setenv("FAKE_INFO_MODE", mode)

    program = await executor.discover(timeout_seconds=1)

    assert program.root is None
    assert program.diagnostics[0].path == ()
    assert program.diagnostics[0].reason == reason
    raw_result = await executor.execute(("raw",))
    assert raw_result.stdout == "raw-ok\n"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("exit", "conda catalog discovery exited with status 23"),
        ("timeout", "conda catalog discovery timed out"),
        (
            "invalid_json",
            "conda catalog discovery returned invalid JSON: JSONDecodeError",
        ),
        (
            "invalid_fields",
            "conda catalog discovery returned invalid program fields",
        ),
        (
            "version_mismatch",
            "conda catalog discovery reported a different conda version",
        ),
    ],
)
async def test_discover_returns_unavailable_program_for_target_failure(
    discovery_executor: tuple[CondaExecutor, Path],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    reason: str,
) -> None:
    executor, _marker = discovery_executor
    monkeypatch.setenv("FAKE_DISCOVERY_MODE", mode)

    program = await executor.discover(timeout_seconds=1)

    assert program.conda_version == "99.1"
    assert program.root is None
    assert program.diagnostics[0].path == ()
    assert program.diagnostics[0].reason == reason
    raw_result = await executor.execute(("raw",))
    assert raw_result.stdout == "raw-ok\n"


@pytest.mark.anyio
async def test_discover_returns_unavailable_program_for_interpreter_failure(
    discovery_executor: tuple[CondaExecutor, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor, _marker = discovery_executor
    interpreter = tmp_path / "not-an-interpreter"
    interpreter.write_text("")
    monkeypatch.setenv("FAKE_TARGET_PYTHON", str(interpreter))

    program = await executor.discover()

    assert program.conda_version == "99.1"
    assert program.diagnostics[0].reason.startswith(
        "conda target interpreter could not start:"
    )


@pytest.mark.anyio
async def test_discover_propagates_caller_cancellation(
    discovery_executor: tuple[CondaExecutor, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, _marker = discovery_executor
    monkeypatch.setenv("FAKE_DISCOVERY_MODE", "timeout")

    with anyio.move_on_after(0.1) as cancel_scope:
        await executor.discover()

    assert cancel_scope.cancel_called
    raw_result = await executor.execute(("raw",))
    assert raw_result.stdout == "raw-ok\n"


@pytest.mark.anyio
async def test_discover_live_conda_installation() -> None:
    conda = shutil.which("conda")
    if conda is None:
        pytest.skip("conda is not installed")
    executor = CondaExecutor(Path(conda), timeout_seconds=30)

    info_result = await executor.execute(("info", "--json"))
    program = await executor.discover()

    assert isinstance(info_result.parsed_json, dict)
    assert program.conda_version == info_result.parsed_json["conda_version"]
    assert program.root is not None
    assert {"env", "info", "install"} <= {child.name for child in program.root.children}
