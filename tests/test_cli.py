from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from conda_cli_mcp.cli import create_parser, main

if TYPE_CHECKING:
    from pathlib import Path


def test_create_parser_accepts_server_options() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "--conda-exe",
            "/tmp/conda",
            "--timeout",
            "12",
            "--output-limit-bytes",
            "2048",
            "--stdin-limit-bytes",
            "1024",
            "--allow-write",
            "--allow-exec",
        ]
    )

    assert parser.prog == "ccm"
    assert args.conda_exe == "/tmp/conda"
    assert args.timeout == 12
    assert args.output_limit_bytes == 2048
    assert args.stdin_limit_bytes == 1024
    assert args.allow_write
    assert args.allow_exec


def test_main_explains_conda_resolution_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--conda-exe", str(tmp_path / "missing-conda")])

    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert "--conda-exe" in error
    assert "CONDA_EXE" in error
    assert "PATH" in error


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--timeout", "0"),
        ("--timeout", "-1"),
        ("--timeout", "inf"),
        ("--timeout", "nan"),
        ("--output-limit-bytes", "0"),
        ("--output-limit-bytes", "-1"),
        ("--stdin-limit-bytes", "0"),
    ],
)
def test_create_parser_rejects_unbounded_limits(option: str, value: str) -> None:
    with pytest.raises(SystemExit) as caught:
        create_parser().parse_args([option, value])

    assert caught.value.code == 2


def test_main_rejects_batch_launchers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher = tmp_path / "conda.cmd"
    launcher.touch(mode=0o755)

    with pytest.raises(SystemExit) as caught:
        main(["--conda-exe", str(launcher)])

    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert "conda.exe" in error
    assert "--conda-exe" in error
