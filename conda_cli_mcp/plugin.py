from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from conda.plugins import hookimpl

if TYPE_CHECKING:
    from collections.abc import Iterable

    from conda.plugins.types import CondaSubcommand


def run_mcp(argv: tuple[str, ...]) -> None:
    """Replace the invoking conda process with the MCP server."""
    from conda.base.context import context
    from conda.exceptions import CondaError

    if context.dev:
        raise CondaError("conda mcp requires an installed conda executable")

    conda_executable = context.conda_exe_vars_dict["CONDA_EXE"]
    if not conda_executable:
        raise CondaError("the invoking conda executable is unavailable")

    command = (
        sys.executable,
        "-m",
        "conda_cli_mcp",
        "--conda-exe",
        conda_executable,
        *argv,
    )

    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import subprocess

        from .windows import CREATE_SUSPENDED, WindowsJob

        windows_job = WindowsJob()
        process = None
        try:
            process = subprocess.Popen(command, creationflags=CREATE_SUSPENDED)
            windows_job.assign_and_resume(process.pid)
            return_code = process.wait()
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            windows_job.close()
        raise SystemExit(return_code)
    os.execv(sys.executable, command)


@hookimpl
def conda_subcommands() -> Iterable[CondaSubcommand]:
    """Register the ``conda mcp`` subcommand."""
    from conda.plugins.types import CondaSubcommand

    yield CondaSubcommand(
        name="mcp",
        summary="Expose conda and its plugin commands through MCP.",
        action=run_mcp,
    )
