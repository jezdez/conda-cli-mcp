from __future__ import annotations

import argparse
import math
from dataclasses import replace
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from collections.abc import Sequence

from . import __version__
from .capabilities import Capabilities
from .execution import CondaExecutor
from .models import Diagnostic
from .policy import SafetyPolicy
from .server import CondaMCPServer


def positive_finite_float(value: str) -> float:
    """Parse one finite, positive floating-point CLI value."""
    parsed = float(value)
    if parsed <= 0 or not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


def positive_int(value: str) -> int:
    """Parse one positive integer CLI value."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def create_parser() -> argparse.ArgumentParser:
    """Create the conda-cli-mcp command-line parser."""
    parser = argparse.ArgumentParser(
        prog="conda-cli-mcp",
        description="Expose an installed conda CLI through MCP.",
    )
    parser.add_argument(
        "--conda-exe",
        help="Path to conda. Defaults to CONDA_EXE or the executable on PATH.",
    )
    parser.add_argument(
        "--timeout",
        type=positive_finite_float,
        default=900,
        help="Maximum discovery and command timeout in seconds.",
    )
    parser.add_argument(
        "--output-limit-bytes",
        type=positive_int,
        default=1_048_576,
        help="Maximum bytes retained from each output stream.",
    )
    parser.add_argument(
        "--stdin-limit-bytes",
        type=positive_int,
        default=1_048_576,
        help="Maximum bytes accepted as non-interactive input.",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="Allow conda operations that mutate environments or files.",
    )
    parser.add_argument(
        "--allow-exec",
        action="store_true",
        help="Expose raw argv execution and allow conda run.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


async def serve(
    executor: CondaExecutor,
    policy: SafetyPolicy = SafetyPolicy(),
) -> None:
    """Discover the target conda CLI and serve it over standard I/O."""
    program = await executor.discover()
    try:
        plugins = await executor.discover_plugins()
    except RuntimeError as error:
        program = replace(
            program,
            diagnostics=(
                *program.diagnostics,
                Diagnostic(path=(), reason=str(error)[:512]),
            ),
        )
        plugins = ()
    capabilities = Capabilities(
        target_executable=str(executor.executable),
        program=program,
        plugins=plugins,
    )
    await CondaMCPServer(executor, capabilities, policy).run_stdio()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the configured MCP server."""
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        executor = CondaExecutor.from_environment(
            args.conda_exe,
            timeout_seconds=args.timeout,
            output_limit_bytes=args.output_limit_bytes,
            stdin_limit_bytes=args.stdin_limit_bytes,
        )
    except FileNotFoundError:
        parser.error(
            "could not find conda. Use --conda-exe, set CONDA_EXE, or add conda to PATH"
        )
    except ValueError as error:
        parser.error(str(error))
    policy = SafetyPolicy(
        allow_write=args.allow_write,
        allow_exec=args.allow_exec,
    )
    anyio.run(serve, executor, policy, backend="asyncio")
