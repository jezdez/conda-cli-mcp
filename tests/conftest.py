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
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

command = sys.argv[1]
if command == "json":
    print(json.dumps({"argv": sys.argv[2:]}))
elif command == "literal":
    sys.stdout.write(sys.argv[2])
elif command == "streams":
    print("stdout-value")
    print("stderr-value", file=sys.stderr)
    raise SystemExit(7)
elif command == "large-streams":
    size = int(sys.argv[2])
    sys.stdout.buffer.write(b"o" * size)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(b"e" * size)
    sys.stderr.buffer.flush()
elif command == "stdin":
    print(sys.stdin.read())
elif command == "cwd":
    print(Path.cwd())
elif command == "linger":
    started = Path(sys.argv[2])
    survived = Path(sys.argv[3])
    if os.name != "nt":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    started.write_text("started")
    time.sleep(float(sys.argv[4]))
    survived.write_text("survived")
elif command == "inherited-pipes":
    subprocess.Popen([
        sys.executable,
        "-c",
        "import sys, time\\n"
        "from pathlib import Path\\n"
        "time.sleep(0.5)\\n"
        "Path(sys.argv[1]).write_text('survived')",
        sys.argv[2],
    ])
elif command == "serialize":
    log = Path(sys.argv[2])
    token = sys.argv[3]
    with log.open("a") as stream:
        stream.write(f"start-{token}\\n")
    time.sleep(float(sys.argv[4]))
    with log.open("a") as stream:
        stream.write(f"end-{token}\\n")
"""
    )
    return CondaExecutor(Path(sys.executable), timeout_seconds=2), script
