from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import anyio

from .models import Diagnostic, ExecutionResult, Program

if TYPE_CHECKING:
    from .models import JsonValue


@dataclass(slots=True)
class CondaExecutor:
    """Run commands against one explicitly resolved conda executable."""

    executable: Path
    timeout_seconds: float = 900
    _lock: anyio.Lock = field(default_factory=anyio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.executable = self.executable.expanduser().resolve()
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not self.executable.is_file():
            raise FileNotFoundError(self.executable)

    @classmethod
    def from_environment(
        cls,
        executable: str | os.PathLike[str] | None = None,
        *,
        timeout_seconds: float = 900,
    ) -> CondaExecutor:
        """Resolve conda from an explicit path, CONDA_EXE, or PATH."""
        candidate = (
            os.fspath(executable) if executable is not None else os.getenv("CONDA_EXE")
        )
        resolved = shutil.which(candidate or "conda")
        if resolved is None:
            raise FileNotFoundError(candidate or "conda")
        return cls(Path(resolved), timeout_seconds=timeout_seconds)

    async def execute(
        self,
        argv: list[str] | tuple[str, ...],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Execute *argv* without a shell and capture its complete result."""
        timeout = (
            timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        )
        if timeout <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if cwd is not None and not cwd.is_dir():
            raise NotADirectoryError(cwd)

        started = time.monotonic()
        async with self._lock:
            try:
                with anyio.fail_after(timeout):
                    completed = await anyio.run_process(
                        [str(self.executable), *argv],
                        input=stdin.encode() if stdin is not None else None,
                        stdin=None if stdin is not None else subprocess.DEVNULL,
                        cwd=cwd,
                        check=False,
                    )
            except TimeoutError:
                return ExecutionResult(
                    exit_code=None,
                    stdout="",
                    stderr="",
                    duration_ms=round((time.monotonic() - started) * 1000),
                    timed_out=True,
                )

        stdout = (completed.stdout or b"").decode(errors="replace")
        stderr = (completed.stderr or b"").decode(errors="replace")
        parsed_json: JsonValue | None = None
        if stdout.strip():
            try:
                parsed_json = json.loads(stdout)
            except json.JSONDecodeError:
                pass

        return ExecutionResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=round((time.monotonic() - started) * 1000),
            parsed_json=parsed_json,
        )

    async def discover(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> Program:
        """Discover the CLI catalog in this conda installation."""
        timeout = (
            timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        )
        if timeout <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        def unavailable(reason: str, conda_version: str = "unknown") -> Program:
            return Program(
                prog=self.executable.name or "conda",
                conda_version=conda_version,
                root=None,
                diagnostics=(Diagnostic(path=(), reason=reason[:512]),),
            )

        try:
            info_result = await self.execute(
                ("info", "--json"),
                timeout_seconds=timeout,
            )
        except OSError as error:
            return unavailable(f"conda info could not start: {type(error).__name__}")

        if info_result.timed_out:
            return unavailable("conda info timed out")
        if info_result.exit_code != 0:
            return unavailable(f"conda info exited with status {info_result.exit_code}")
        if not isinstance(info_result.parsed_json, dict):
            return unavailable("conda info did not return a JSON object")

        info = info_result.parsed_json
        conda_version = info.get("conda_version")
        if not isinstance(conda_version, str) or not conda_version:
            return unavailable("conda info field 'conda_version' is missing or invalid")

        interpreter_value = info.get("sys.executable")
        if not isinstance(interpreter_value, str) or not interpreter_value:
            return unavailable(
                "conda info field 'sys.executable' is missing or invalid",
                conda_version,
            )
        interpreter = Path(interpreter_value).expanduser()
        if not interpreter.is_file():
            return unavailable(
                "conda target interpreter is not a file",
                conda_version,
            )

        package_root = str(Path(__file__).resolve().parent.parent)
        environment = os.environ.copy()
        python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            os.pathsep.join((package_root, python_path))
            if python_path
            else package_root
        )

        try:
            async with self._lock:
                with anyio.fail_after(timeout):
                    completed = await anyio.run_process(
                        [
                            str(interpreter),
                            "-m",
                            "conda_cli_mcp.discovery",
                        ],
                        stdin=subprocess.DEVNULL,
                        env=environment,
                        check=False,
                    )
        except TimeoutError:
            return unavailable("conda catalog discovery timed out", conda_version)
        except OSError as error:
            return unavailable(
                f"conda target interpreter could not start: {type(error).__name__}",
                conda_version,
            )

        if completed.returncode != 0:
            return unavailable(
                f"conda catalog discovery exited with status {completed.returncode}",
                conda_version,
            )

        stdout = (completed.stdout or b"").decode(errors="replace")
        try:
            program = Program.from_json(stdout)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            return unavailable(
                "conda catalog discovery returned invalid JSON: "
                f"{type(error).__name__}",
                conda_version,
            )

        if program.conda_version != conda_version:
            return unavailable(
                "conda catalog discovery reported a different conda version",
                conda_version,
            )
        if (
            not isinstance(program.prog, str)
            or not program.prog
            or program.root is None
        ):
            return unavailable(
                "conda catalog discovery returned invalid program fields",
                conda_version,
            )
        return program
