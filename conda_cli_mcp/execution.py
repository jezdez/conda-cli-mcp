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

from .models import ExecutionResult

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
