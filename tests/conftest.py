from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conda_cli_mcp.execution import CondaExecutor


@pytest.fixture
def fake_conda(tmp_path: Path) -> tuple[CondaExecutor, Path]:
    script = tmp_path / "fake_conda.py"
    script.write_text(
        """\
import json
import sys
import time

command = sys.argv[1]
if command == "json":
    print(json.dumps({"argv": sys.argv[2:]}))
elif command == "streams":
    print("stdout-value")
    print("stderr-value", file=sys.stderr)
    raise SystemExit(7)
elif command == "stdin":
    print(sys.stdin.read())
elif command == "sleep":
    time.sleep(float(sys.argv[2]))
elif command == "cwd":
    from pathlib import Path
    print(Path.cwd())
"""
    )
    return CondaExecutor(Path(sys.executable), timeout_seconds=2), script
