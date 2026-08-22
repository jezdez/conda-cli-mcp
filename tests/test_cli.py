from __future__ import annotations

from conda_cli_mcp.cli import create_parser


def test_create_parser_accepts_server_options() -> None:
    args = create_parser().parse_args(["--conda-exe", "/tmp/conda", "--timeout", "12"])

    assert args.conda_exe == "/tmp/conda"
    assert args.timeout == 12
