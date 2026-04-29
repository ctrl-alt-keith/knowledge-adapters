from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cli_command() -> list[str]:
    repo_local_cli = _repo_root() / ".venv" / "bin" / "knowledge-adapters"
    if repo_local_cli.exists():
        return [str(repo_local_cli)]

    return [sys.executable, "-m", "knowledge_adapters.cli"]


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_cli_command(), *args],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
