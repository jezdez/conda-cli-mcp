from __future__ import annotations

import asyncio
import codecs
import json
import math
import os
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import anyio

from .models import Diagnostic, ExecutionResult, Plugin, Program

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from .models import JsonValue


class DiscoveryError(RuntimeError):
    """Report a target discovery failure without exposing subprocess output."""

    def __init__(self, reason: str, conda_version: str = "unknown") -> None:
        super().__init__(reason)
        self.conda_version = conda_version


class CompletionQueryError(RuntimeError):
    """Report a bounded conda-completion query failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class CondaExecutor:
    """Run commands against one explicitly resolved conda executable."""

    executable: Path
    timeout_seconds: float = 900
    output_limit_bytes: int = 1_048_576
    stdin_limit_bytes: int = 1_048_576
    termination_grace_seconds: float = 2
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.executable = self.executable.expanduser().resolve()
        if self.timeout_seconds <= 0 or not math.isfinite(self.timeout_seconds):
            raise ValueError("timeout_seconds must be finite and greater than zero")
        if self.output_limit_bytes <= 0:
            raise ValueError("output_limit_bytes must be greater than zero")
        if self.stdin_limit_bytes <= 0:
            raise ValueError("stdin_limit_bytes must be greater than zero")
        if self.termination_grace_seconds <= 0 or not math.isfinite(
            self.termination_grace_seconds
        ):
            raise ValueError(
                "termination_grace_seconds must be finite and greater than zero"
            )
        if not self.executable.is_file():
            raise FileNotFoundError(self.executable)
        if self.executable.suffix.casefold() in {".bat", ".cmd"}:
            raise ValueError(
                "conda batch launchers are not supported. "
                "Select conda.exe with --conda-exe"
            )

    @classmethod
    def from_environment(
        cls,
        executable: str | os.PathLike[str] | None = None,
        *,
        timeout_seconds: float = 900,
        output_limit_bytes: int = 1_048_576,
        stdin_limit_bytes: int = 1_048_576,
        termination_grace_seconds: float = 2,
    ) -> CondaExecutor:
        """Resolve conda from an explicit path, CONDA_EXE, or PATH."""
        candidate = (
            os.fspath(executable) if executable is not None else os.getenv("CONDA_EXE")
        )
        default_executable = "conda.exe" if os.name == "nt" else "conda"
        resolved = shutil.which(candidate or default_executable)
        if resolved is None:
            raise FileNotFoundError(candidate or default_executable)
        return cls(
            Path(resolved),
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
            stdin_limit_bytes=stdin_limit_bytes,
            termination_grace_seconds=termination_grace_seconds,
        )

    async def execute(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Execute *argv* without a shell and capture a bounded result."""
        timeout = self.bounded_timeout(timeout_seconds)
        if cwd is not None and not cwd.is_dir():
            raise NotADirectoryError(cwd)
        stdin_bytes = stdin.encode() if stdin is not None else None
        if stdin_bytes is not None and len(stdin_bytes) > self.stdin_limit_bytes:
            raise ValueError(
                f"stdin exceeds the {self.stdin_limit_bytes}-byte input limit"
            )

        return await self._execute_process(
            (str(self.executable), *argv),
            cwd=cwd,
            stdin=stdin_bytes,
            timeout=timeout,
        )

    def bounded_timeout(self, timeout_seconds: float | None = None) -> float:
        """Return a valid timeout no greater than the server limit."""
        timeout = (
            timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        )
        if timeout <= 0 or not math.isfinite(timeout):
            raise ValueError("timeout_seconds must be finite and greater than zero")
        return min(timeout, self.timeout_seconds)

    async def discover(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> Program:
        """Discover the CLI catalog in this conda installation."""
        timeout = self.bounded_timeout(timeout_seconds)

        def unavailable(reason: str, conda_version: str = "unknown") -> Program:
            return Program(
                prog=self.executable.name or "conda",
                conda_version=conda_version,
                root=None,
                diagnostics=(Diagnostic(path=(), reason=reason[:512]),),
            )

        try:
            conda_version, stdout = await self._run_discovery_worker((), timeout)
        except DiscoveryError as error:
            return unavailable(str(error), error.conda_version)
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

    async def discover_plugins(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[Plugin, ...]:
        """Discover external conda plugin entry points in the target environment."""
        _, plugins = await self.discover_plugin_state(timeout_seconds=timeout_seconds)
        return plugins

    async def discover_plugin_state(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, tuple[Plugin, ...]]:
        """Return the target conda version and external plugin entry points."""
        timeout = self.bounded_timeout(timeout_seconds)

        conda_version, stdout = await self._run_discovery_worker(
            ("--plugins",), timeout
        )
        try:
            payload = json.loads(stdout)
            if not isinstance(payload, list):
                raise TypeError
            plugins = tuple(Plugin.from_dict(item) for item in payload)
        except (KeyError, TypeError, ValueError) as error:
            raise DiscoveryError(
                f"conda plugin discovery returned invalid JSON: {type(error).__name__}",
                conda_version,
            ) from error
        return conda_version, plugins

    async def inspect_completion_command(
        self,
        command_path: Sequence[str] = (),
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, JsonValue]:
        """Query conda-completion metadata through the target interpreter."""
        timeout = self.bounded_timeout(timeout_seconds)
        request = json.dumps(
            {"command_path": list(command_path)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        _, stdout = await self._run_discovery_worker(
            ("--completion-command", request), timeout
        )

        def reject_constant(value: str) -> None:
            raise ValueError(value)

        try:
            payload = json.loads(stdout, parse_constant=reject_constant)
            if not isinstance(payload, dict):
                raise TypeError
            error = payload.get("error")
            if error is not None:
                if not isinstance(error, str):
                    raise TypeError
                raise CompletionQueryError(error)
        except CompletionQueryError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise CompletionQueryError("invalid_response") from error
        return payload

    async def _run_discovery_worker(
        self,
        arguments: Sequence[str],
        timeout: float,
    ) -> tuple[str, str]:
        try:
            info_result = await self.execute(
                ("info", "--json"), timeout_seconds=timeout
            )
        except OSError as error:
            raise DiscoveryError(
                f"conda info could not start: {type(error).__name__}"
            ) from error
        if info_result.timed_out:
            raise DiscoveryError("conda info timed out")
        if info_result.exit_code != 0:
            raise DiscoveryError(
                f"conda info exited with status {info_result.exit_code}"
            )
        if not isinstance(info_result.parsed_json, dict):
            raise DiscoveryError("conda info did not return a JSON object")

        conda_version = info_result.parsed_json.get("conda_version")
        if not isinstance(conda_version, str) or not conda_version:
            raise DiscoveryError(
                "conda info field 'conda_version' is missing or invalid"
            )
        interpreter_value = info_result.parsed_json.get("sys.executable")
        if not isinstance(interpreter_value, str) or not interpreter_value:
            raise DiscoveryError(
                "conda info field 'sys.executable' is missing or invalid",
                conda_version,
            )
        interpreter = Path(interpreter_value).expanduser()
        if not interpreter.is_file():
            raise DiscoveryError(
                "conda target interpreter is not a file",
                conda_version,
            )

        helper = Path(__file__).resolve().with_name("discovery.py")

        purpose = (
            "conda plugin discovery"
            if arguments[:1] == ("--plugins",)
            else (
                "conda completion metadata"
                if arguments[:1] == ("--completion-command",)
                else "conda catalog discovery"
            )
        )
        try:
            completed = await self._execute_process(
                (
                    str(interpreter),
                    str(helper),
                    *arguments,
                ),
                cwd=None,
                stdin=None,
                timeout=timeout,
            )
        except OSError as error:
            raise DiscoveryError(
                f"conda target interpreter could not start: {type(error).__name__}",
                conda_version,
            ) from error

        if completed.timed_out:
            raise DiscoveryError(
                f"{purpose} timed out",
                conda_version,
            )
        if completed.exit_code != 0:
            raise DiscoveryError(
                f"{purpose} exited with status {completed.exit_code}",
                conda_version,
            )
        return conda_version, completed.stdout

    async def _execute_process(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        stdin: bytes | None,
        timeout: float,
    ) -> ExecutionResult:
        async with self._lock:
            started = time.monotonic()
            windows_job: Any = None
            creation_flags = 0
            if os.name == "nt":
                from .windows import CREATE_SUSPENDED, WindowsJob

                windows_job = WindowsJob()
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
            process_options: dict[str, Any] = (
                {"creationflags": creation_flags}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=(
                        asyncio.subprocess.PIPE
                        if stdin is not None
                        else asyncio.subprocess.DEVNULL
                    ),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    **process_options,
                )
                if windows_job is not None:
                    windows_job.assign_and_resume(process.pid)
            except BaseException:
                if process is not None and process.returncode is None:
                    with suppress(OSError):
                        process.kill()
                    await process.wait()
                if windows_job is not None:
                    windows_job.close()
                raise
            assert process.stdout is not None
            assert process.stderr is not None

            async def capture(
                stream: asyncio.StreamReader,
            ) -> tuple[str, bool]:
                content = bytearray()
                truncated = False
                try:
                    while chunk := await stream.read(65_536):
                        available = self.output_limit_bytes - len(content)
                        if available > 0:
                            content.extend(chunk[:available])
                        if len(chunk) > available:
                            truncated = True
                except asyncio.CancelledError:
                    truncated = True
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                return decoder.decode(content, final=not truncated), truncated

            async def send_input() -> None:
                if process.stdin is None or stdin is None:
                    return
                try:
                    process.stdin.write(stdin)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()
                    with suppress(BrokenPipeError, ConnectionResetError):
                        await process.stdin.wait_closed()

            stdout_task = asyncio.create_task(capture(process.stdout))
            stderr_task = asyncio.create_task(capture(process.stderr))
            input_task = asyncio.create_task(send_input())
            wait_task = asyncio.create_task(process.wait())
            tasks = (wait_task, stdout_task, stderr_task, input_task)

            async def stop_process() -> None:
                if os.name == "nt":
                    with suppress(OSError):
                        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
                else:
                    with suppress(OSError):
                        os.killpg(process.pid, signal.SIGTERM)
                try:
                    if not wait_task.done():
                        await asyncio.wait_for(
                            asyncio.shield(wait_task),
                            self.termination_grace_seconds,
                        )
                except asyncio.TimeoutError:
                    pass

                if os.name == "nt":
                    assert windows_job is not None
                    windows_job.terminate()
                else:
                    with suppress(OSError):
                        os.killpg(process.pid, signal.SIGKILL)
                if not wait_task.done():
                    await wait_task

            timed_out = False
            try:
                _, pending = await asyncio.wait(tasks, timeout=timeout)
                if pending:
                    timed_out = True
                    with anyio.CancelScope(shield=True):
                        await stop_process()
                        for task in (stdout_task, stderr_task, input_task):
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                stdout_result, stderr_result, _ = await asyncio.gather(
                    stdout_task,
                    stderr_task,
                    input_task,
                )
            except asyncio.CancelledError:
                with anyio.CancelScope(shield=True):
                    await stop_process()
                    for task in (stdout_task, stderr_task, input_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                raise
            finally:
                if windows_job is not None:
                    windows_job.close()

        stdout, stdout_truncated = stdout_result
        stderr, stderr_truncated = stderr_result
        parsed_json: JsonValue | None = None
        if stdout.strip() and not stdout_truncated:

            def reject_constant(value: str) -> None:
                raise ValueError(value)

            try:
                parsed_json = json.loads(stdout, parse_constant=reject_constant)
            except (json.JSONDecodeError, ValueError):
                pass

        return ExecutionResult(
            exit_code=None if timed_out else process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=round((time.monotonic() - started) * 1000),
            parsed_json=parsed_json,
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
