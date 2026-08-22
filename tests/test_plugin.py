from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

import conda.base.context as conda_context
import pytest
from conda.exceptions import CondaError

from conda_cli_mcp import plugin

if TYPE_CHECKING:
    from collections.abc import Sequence


def test_registers_one_opaque_mcp_subcommand() -> None:
    (subcommand,) = plugin.conda_subcommands()

    assert subcommand.name == "mcp"
    assert subcommand.aliases == ()
    assert subcommand.configure_parser is None
    assert subcommand.action is plugin.run_mcp


def test_run_mcp_replaces_native_process_with_forwarded_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Sequence[str]]] = []

    def record_execv(executable: str, argv: Sequence[str]) -> None:
        calls.append((executable, argv))

    monkeypatch.setattr(
        conda_context,
        "context",
        SimpleNamespace(
            dev=False,
            conda_exe_vars_dict={
                "CONDA_EXE": "/runtime/bin/conda",
            },
        ),
    )
    monkeypatch.setattr(
        plugin,
        "os",
        SimpleNamespace(name="posix", execv=record_execv),
    )

    plugin.run_mcp(("--allow-write", "--timeout", "30"))

    assert calls == [
        (
            sys.executable,
            (
                sys.executable,
                "-m",
                "conda_cli_mcp",
                "--conda-exe",
                "/runtime/bin/conda",
                "--allow-write",
                "--timeout",
                "30",
            ),
        )
    ]


def test_run_mcp_propagates_windows_process_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class Process:
        pid = 42

        def wait(self) -> int:
            calls.append(("wait", self))
            return 17

    class Job:
        def assign_and_resume(self, pid: int) -> None:
            calls.append(("assign", pid))

        def close(self) -> None:
            calls.append(("close", self))

    process = Process()
    job = Job()

    def record_popen(
        command: Sequence[str],
        *,
        creationflags: int,
    ) -> Process:
        calls.append(("popen", (command, creationflags)))
        return process

    monkeypatch.setattr(
        conda_context,
        "context",
        SimpleNamespace(
            dev=False,
            conda_exe_vars_dict={
                "CONDA_EXE": "C:\\runtime\\Scripts\\conda.exe",
            },
        ),
    )
    monkeypatch.setattr(plugin, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(
        sys.modules,
        "subprocess",
        SimpleNamespace(Popen=record_popen),
    )
    monkeypatch.setitem(
        sys.modules,
        "conda_cli_mcp.windows",
        SimpleNamespace(CREATE_SUSPENDED=4, WindowsJob=lambda: job),
    )

    with pytest.raises(SystemExit) as caught:
        plugin.run_mcp(("--allow-exec",))

    assert caught.value.code == 17
    assert calls == [
        (
            "popen",
            (
                (
                    sys.executable,
                    "-m",
                    "conda_cli_mcp",
                    "--conda-exe",
                    "C:\\runtime\\Scripts\\conda.exe",
                    "--allow-exec",
                ),
                4,
            ),
        ),
        ("assign", 42),
        ("wait", process),
        ("close", job),
    ]


def test_run_mcp_requires_invoking_conda_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conda_context,
        "context",
        SimpleNamespace(dev=False, conda_exe_vars_dict={"CONDA_EXE": None}),
    )

    with pytest.raises(CondaError, match="invoking conda executable"):
        plugin.run_mcp(())


def test_run_mcp_rejects_development_mode_conda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conda_context,
        "context",
        SimpleNamespace(dev=True),
    )

    with pytest.raises(CondaError, match="installed conda executable"):
        plugin.run_mcp(())
