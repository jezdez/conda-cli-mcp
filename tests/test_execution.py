from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest

from conda_cli_mcp.execution import CompletionQueryError, CondaExecutor

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
if python_path != [target_modules]:
    raise RuntimeError("PYTHONPATH was changed")
if sys.path[0] != package_root or target_modules not in sys.path:
    raise RuntimeError("helper script or target modules missing from sys.path")

main_spec = getattr(sys.modules["__main__"], "__spec__", None)
marker = {
    "module": getattr(main_spec, "name", None),
    "pythonpath": python_path,
    "sys_path": sys.path,
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

    completion_package = target_modules / "conda_completion"
    completion_package.mkdir()
    (completion_package / "__init__.py").write_text("")
    (completion_package / "exceptions.py").write_text(
        "class ManifestError(RuntimeError):\n    pass\n"
    )
    (completion_package / "paths.py").write_text(
        """\
import os
from pathlib import Path


def manifest_path():
    return Path(os.environ["FAKE_COMPLETION_PATH"])
"""
    )
    (completion_package / "plugin.py").write_text(
        """\
import os


def plugin_entry_point_hash():
    return os.environ["FAKE_COMPLETION_HASH"]
"""
    )
    (completion_package / "manifest.py").write_text(
        """\
import os
from types import SimpleNamespace


class Spec:
    def __init__(self, **values):
        self.values = values

    def to_dict(self):
        return self.values


class Command:
    def __init__(self, summary, *, options=None, positionals=None, subcommands=None):
        self.summary = summary
        self.options = options or {}
        self.positionals = positionals or []
        self.subcommands = subcommands or {}
        self.exclusive_groups = []


def read_manifest(path):
    mode = os.environ.get("FAKE_COMPLETION_MODE", "available")
    if mode == "missing":
        raise FileNotFoundError(path)
    option = {"short": "-n", "completion_type": "env_name"}
    if mode == "nonstandard_json":
        option["default"] = float("nan")
    leaf = Command(
        "List environments",
        options={"--name": Spec(**option)},
    )
    return SimpleNamespace(
        version=1,
        generated_at="2026-08-22T12:00:00Z",
        plugin_hash="target-hash",
        root_options={},
        commands={"env": Command("Manage environments", subcommands={"list": leaf})},
        aliases={},
        runtime_sources={},
    )
"""
    )
    completion_dist = target_modules / "conda_completion-0.3.0.dist-info"
    completion_dist.mkdir()
    (completion_dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: conda-completion\nVersion: 0.3.0\n"
    )

    marker = tmp_path / "target-marker.json"
    (tmp_path / "discovery.py").write_text(
        "raise RuntimeError('shadowed discovery helper')\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(target_modules))
    monkeypatch.setenv(
        "FAKE_PACKAGE_ROOT",
        str(Path(__file__).resolve().parent.parent / "conda_cli_mcp"),
    )
    monkeypatch.setenv("FAKE_TARGET_MODULES", str(target_modules))
    monkeypatch.setenv("FAKE_TARGET_MARKER", str(marker))
    monkeypatch.setenv("FAKE_TARGET_PYTHON", sys.executable)
    monkeypatch.setenv("FAKE_COMPLETION_PATH", str(tmp_path / "completion.msgpack"))
    monkeypatch.setenv("FAKE_COMPLETION_HASH", "target-hash")
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
@pytest.mark.parametrize(
    ("stdout", "parsed_json"),
    [
        ('{"value": 1}', {"value": 1}),
        (' \n["one", 2]\t', ["one", 2]),
        ('{"value": 1}\n{"value": 2}', None),
        ('prefix {"value": 1}', None),
        ("NaN", None),
        ("Infinity", None),
        ("-Infinity", None),
    ],
)
async def test_execute_parses_exactly_one_json_document(
    fake_conda: tuple[CondaExecutor, Path],
    stdout: str,
    parsed_json: object,
) -> None:
    executor, script = fake_conda

    result = await executor.execute([str(script), "literal", stdout])

    assert result.stdout == stdout
    assert result.parsed_json == parsed_json


@pytest.mark.anyio
async def test_execute_bounds_and_drains_both_output_streams(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(
        executor.executable,
        output_limit_bytes=1_024,
    )

    result = await executor.execute([str(script), "large-streams", "200000"])

    assert result.exit_code == 0
    assert result.stdout == "o" * 1_024
    assert result.stderr == "e" * 1_024
    assert result.stdout_truncated
    assert result.stderr_truncated
    assert result.parsed_json is None


@pytest.mark.anyio
async def test_execute_truncates_at_a_utf8_character_boundary(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(executor.executable, output_limit_bytes=3)

    result = await executor.execute([str(script), "literal", "éé"])

    assert result.stdout == "é"
    assert result.stdout_truncated
    assert "�" not in result.stdout


@pytest.mark.anyio
async def test_execute_rejects_oversized_stdin_before_spawning(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(executor.executable, stdin_limit_bytes=4)

    with pytest.raises(ValueError, match="4-byte input limit"):
        await executor.execute([str(script), "stdin"], stdin="12345")


@pytest.mark.anyio
@pytest.mark.parametrize("timeout", [0, float("inf"), float("nan")])
async def test_execute_rejects_unbounded_timeout_override(
    fake_conda: tuple[CondaExecutor, Path],
    timeout: float,
) -> None:
    executor, script = fake_conda

    with pytest.raises(ValueError, match="finite and greater than zero"):
        await executor.execute(
            [str(script), "literal", "not-started"], timeout_seconds=timeout
        )


@pytest.mark.anyio
async def test_execute_timeout_kills_a_child_that_ignores_termination(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    started = tmp_path / "timeout-started"
    survived = tmp_path / "timeout-survived"
    executor = CondaExecutor(
        executor.executable,
        timeout_seconds=0.5,
        termination_grace_seconds=0.05,
    )

    result = await executor.execute(
        [str(script), "linger", str(started), str(survived), "1"]
    )
    await asyncio.sleep(1.1)

    assert result.timed_out
    assert result.exit_code is None
    assert started.is_file()
    assert not survived.exists()


@pytest.mark.anyio
async def test_execute_timeout_bounds_inherited_pipe_drain(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    survived = tmp_path / "timeout-descendant-survived"
    started = time.monotonic()

    result = await executor.execute(
        [str(script), "inherited-pipes", str(survived)], timeout_seconds=0.05
    )
    elapsed = time.monotonic() - started
    await asyncio.sleep(0.55)

    assert result.timed_out
    assert elapsed < 0.3
    assert result.stdout_truncated
    assert result.stderr_truncated
    assert not survived.exists()


@pytest.mark.anyio
async def test_execute_cancellation_kills_child_and_propagates(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    started = tmp_path / "cancel-started"
    survived = tmp_path / "cancel-survived"
    executor = CondaExecutor(
        executor.executable,
        termination_grace_seconds=0.05,
    )
    execution = asyncio.create_task(
        executor.execute([str(script), "linger", str(started), str(survived), "1"])
    )
    for _ in range(200):
        if started.exists():
            break
        await asyncio.sleep(0.01)
    assert started.is_file()

    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    await asyncio.sleep(1.1)

    assert not survived.exists()


@pytest.mark.anyio
async def test_execute_cancellation_bounds_inherited_pipe_drain(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    survived = tmp_path / "cancel-descendant-survived"
    execution = asyncio.create_task(
        executor.execute([str(script), "inherited-pipes", str(survived)])
    )
    await asyncio.sleep(0.05)
    assert not execution.done()

    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, 0.2)
    await asyncio.sleep(0.55)

    assert not survived.exists()


@pytest.mark.anyio
async def test_execute_timeout_override_cannot_raise_server_limit(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(executor.executable, timeout_seconds=0.05)

    result = await executor.execute(
        [str(script), "serialize", str(tmp_path / "log"), "one", "0.5"],
        timeout_seconds=10,
    )

    assert result.timed_out


@pytest.mark.anyio
async def test_executor_serializes_processes(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    log = tmp_path / "execution-order"

    await asyncio.gather(
        executor.execute([str(script), "serialize", str(log), "one", "0.1"]),
        executor.execute([str(script), "serialize", str(log), "two", "0.1"]),
    )

    assert log.read_text().splitlines() in (
        ["start-one", "end-one", "start-two", "end-two"],
        ["start-two", "end-two", "start-one", "end-one"],
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": float("nan")},
        {"output_limit_bytes": 0},
        {"stdin_limit_bytes": 0},
        {"termination_grace_seconds": 0},
        {"termination_grace_seconds": float("inf")},
        {"termination_grace_seconds": float("nan")},
    ],
)
def test_executor_rejects_invalid_limits(
    tmp_path: Path,
    arguments: dict[str, float],
) -> None:
    executable = tmp_path / "conda"
    executable.touch()

    with pytest.raises(ValueError, match="greater than zero"):
        CondaExecutor(executable, **arguments)


@pytest.mark.parametrize("suffix", [".bat", ".cmd", ".CMD"])
def test_executor_rejects_batch_launchers(tmp_path: Path, suffix: str) -> None:
    executable = tmp_path / f"conda{suffix}"
    executable.touch()

    with pytest.raises(ValueError, match="conda.exe"):
        CondaExecutor(executable)


@pytest.mark.anyio
async def test_discover_uses_target_interpreter_and_absolute_helper(
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
    helper_root = str(Path(__file__).resolve().parent.parent / "conda_cli_mcp")
    assert marker["module"] is None
    assert marker["pythonpath"] == [os.environ["FAKE_TARGET_MODULES"]]
    assert marker["sys_path"][0] == helper_root
    assert os.environ["FAKE_TARGET_MODULES"] in marker["sys_path"]


@pytest.mark.anyio
async def test_inspect_completion_command_uses_target_public_api(
    discovery_executor: tuple[CondaExecutor, Path],
) -> None:
    executor, _marker_path = discovery_executor

    result = await executor.inspect_completion_command(("env", "list"))

    assert result["availability"] == "available"
    assert result["resolved_command_path"] == ["env", "list"]
    assert result["command"]["options"] == [
        {
            "name": "--name",
            "short": "-n",
            "completion_type": "env_name",
        }
    ]
    assert result["manifest"]["conda_completion_version"] == "0.3.0"
    assert result["manifest"]["stale"] is False


@pytest.mark.anyio
async def test_inspect_completion_command_reports_unknown_path(
    discovery_executor: tuple[CondaExecutor, Path],
) -> None:
    executor, _marker_path = discovery_executor

    with pytest.raises(CompletionQueryError) as caught:
        await executor.inspect_completion_command(("unknown",))

    assert caught.value.code == "unknown_command"


@pytest.mark.anyio
async def test_inspect_completion_command_rejects_nonstandard_json(
    discovery_executor: tuple[CondaExecutor, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, _marker_path = discovery_executor
    monkeypatch.setenv("FAKE_COMPLETION_MODE", "nonstandard_json")

    with pytest.raises(CompletionQueryError) as caught:
        await executor.inspect_completion_command(("env", "list"))

    assert caught.value.code == "invalid_response"


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


@pytest.mark.anyio
async def test_shell_activation_returns_code_without_mutating_server_environment() -> (
    None
):
    conda = shutil.which("conda")
    if conda is None:
        pytest.skip("conda is not installed")
    executor = CondaExecutor(Path(conda), timeout_seconds=30)
    previous_prefix = os.environ.get("CONDA_PREFIX")

    result = await executor.execute(("shell.posix", "activate"))

    assert result.exit_code == 0
    assert result.stdout
    assert os.environ.get("CONDA_PREFIX") == previous_prefix
