from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from collections.abc import Sequence

from . import __version__
from .execution import CondaExecutor
from .server import CondaMCPServer


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
        type=float,
        default=900,
        help="Default command timeout in seconds.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


async def serve(executor: CondaExecutor) -> None:
    """Discover the target conda CLI and serve it over standard I/O."""
    program = await executor.discover()
    await CondaMCPServer(executor, program).run_stdio()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the configured MCP server."""
    args = create_parser().parse_args(argv)
    executor = CondaExecutor.from_environment(
        args.conda_exe,
        timeout_seconds=args.timeout,
    )
    anyio.run(serve, executor, backend="asyncio")
