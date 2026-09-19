"""Regression coverage for the local development environment bootstrap.

`make check` is this repository's canonical validation entrypoint, so its
interpreter selection and virtual-environment staleness handling are repository
behavior worth protecting. These tests exercise only the paths that fail before
any package installation, so they stay deterministic and need no network.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON_VERSION = "3.13"

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make is not available")


def _run_make(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", *arguments],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_env_selects_an_interpreter_satisfying_requires_python() -> None:
    result = _run_make("check-env")

    assert result.returncode == 0, result.stderr
    assert "Using " in result.stdout


def test_check_env_rejects_an_explicit_interpreter_below_requires_python() -> None:
    if shutil.which("python3.11") is None:
        pytest.skip("no older interpreter available to reject")

    result = _run_make("check-env", "PYTHON_BIN=python3.11")

    assert result.returncode != 0
    assert MIN_PYTHON_VERSION in result.stderr


def test_check_env_rejects_a_missing_explicit_interpreter() -> None:
    result = _run_make("check-env", "PYTHON_BIN=python-does-not-exist")

    assert result.returncode != 0
    assert "python-does-not-exist" in result.stderr


def test_bootstrap_does_not_reuse_an_environment_left_by_a_failed_install(
    tmp_path: Path,
) -> None:
    """An interrupted install leaves a venv behind; it must not look ready."""
    stale_venv = tmp_path / "stale-venv"
    (stale_venv / "bin").mkdir(parents=True)
    # The previous bootstrap wrote this before installing, so its presence alone
    # never meant the environment was usable.
    (stale_venv / "bin" / "activate").touch()

    result = _run_make("dev", f"VENV={stale_venv}")

    assert result.returncode != 0
    assert "Nothing to be done" not in result.stdout
    assert "make clean" in result.stderr
    assert not (stale_venv / ".dev-install-complete").exists()
