"""Runtime source identity diagnostics for adapter run reports."""

from __future__ import annotations

import subprocess
import sys
from importlib import metadata
from pathlib import Path

import knowledge_adapters


def adapter_runtime_identity() -> dict[str, object]:
    """Return machine-readable runtime identity for diagnostic run output."""
    module_path = Path(knowledge_adapters.__file__).resolve()
    return {
        "package_name": "knowledge-adapters",
        "package_version": _package_version(),
        "module": "knowledge_adapters.cli:main",
        "module_path": module_path.as_posix(),
        "git_sha": _git_sha(module_path.parent),
        "executable_path": Path(sys.executable).resolve().as_posix(),
        "entry_point": "knowledge-adapters",
    }


def _package_version() -> str:
    try:
        return metadata.version("knowledge-adapters")
    except metadata.PackageNotFoundError:
        return getattr(knowledge_adapters, "__version__", "unknown")


def _git_sha(path: Path) -> str | None:
    try:
        completed = subprocess.run(
            ("git", "-C", str(path), "rev-parse", "HEAD"),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    sha = completed.stdout.strip()
    return sha or None

