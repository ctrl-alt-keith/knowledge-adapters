"""Regression coverage for the local development environment bootstrap.

`make check` is this repository's canonical validation entrypoint, so its
interpreter selection and virtual-environment staleness handling are repository
behavior worth protecting. These tests exercise only the paths that fail before
any package installation, so they stay deterministic and need no network.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
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


def _environment_built_by_another_interpreter(tmp_path: Path) -> Path:
    """A stand-in environment that reports a different base interpreter.

    Exercising the guard needs two distinguishable base interpreters, and a host
    is only guaranteed to have one that satisfies requires-python. The stub
    answers the base-interpreter probe with a different path and delegates every
    other call, so the branch is reachable without a second real interpreter.
    """
    venv = tmp_path / "other-venv"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *_base_executable*) echo "/nonexistent/other-python" ;;\n'
        f'  *) exec {sys.executable} "$@" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return venv


@pytest.mark.parametrize("already_installed", [False, True])
def test_explicit_interpreter_is_not_ignored_for_an_existing_environment(
    tmp_path: Path, already_installed: bool
) -> None:
    """An explicit PYTHON_BIN must never be silently discarded.

    The completed-install case matters most: the stamp is up to date there, so a
    recipe-level check never runs and the selection would otherwise be dropped.
    """
    venv = _environment_built_by_another_interpreter(tmp_path)
    if already_installed:
        (venv / ".dev-install-complete").touch()

    result = _run_make("dev", f"VENV={venv}", f"PYTHON_BIN={sys.executable}")

    assert result.returncode != 0
    assert "make clean" in result.stderr
    assert "/nonexistent/other-python" in result.stderr


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
