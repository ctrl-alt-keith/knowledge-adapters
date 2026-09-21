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
    # A stamped environment must otherwise look complete, or the readiness check
    # rejects it for a missing tool before the interpreter comparison is reached.
    for tool in INVOKED_TOOLS:
        stub = venv / "bin" / tool
        stub.write_text("#!/bin/sh\n", encoding="utf-8")
        stub.chmod(0o755)
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


INVOKED_TOOLS = ("pip", "ruff", "mypy", "pytest")


def _completed_environment(tmp_path: Path, *, missing: str | None = None) -> Path:
    """An environment whose stamp says the install finished."""
    venv = tmp_path / "complete-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    for tool in INVOKED_TOOLS:
        if tool == missing:
            continue
        stub = venv / "bin" / tool
        stub.write_text("#!/bin/sh\n", encoding="utf-8")
        stub.chmod(0o755)
    (venv / ".dev-install-complete").touch()
    return venv


@pytest.mark.parametrize("missing", INVOKED_TOOLS)
def test_a_stamp_is_rejected_when_an_invoked_tool_is_missing(tmp_path: Path, missing: str) -> None:
    """A runnable interpreter is not evidence that the install survived.

    An environment can keep bin/python while losing the tools the stamp claims
    were installed. Accepting that defers the failure to the first target that
    invokes one, which is the missing-tool error this guard exists to prevent.
    """
    venv = _completed_environment(tmp_path, missing=missing)

    result = _run_make("dev", f"VENV={venv}")

    assert result.returncode != 0
    assert missing in result.stderr
    assert "make clean" in result.stderr


def test_a_complete_environment_is_accepted(tmp_path: Path) -> None:
    """The readiness check must not reject an environment that is actually complete."""
    venv = _completed_environment(tmp_path)

    result = _run_make("dev", f"VENV={venv}")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("interpreter_shape", ["missing", "dangling-symlink"])
@pytest.mark.parametrize("explicit_interpreter", [False, True])
def test_a_surviving_stamp_without_a_usable_interpreter_is_rejected(
    tmp_path: Path, interpreter_shape: str, explicit_interpreter: bool
) -> None:
    """A completion stamp can outlive the environment it described.

    A partially removed environment, or one whose base interpreter was upgraded
    out from under its symlink, leaves the stamp current while nothing usable
    remains. Reporting that as ready discards an explicit PYTHON_BIN and defers
    the failure to a confusing missing-tool error later in validation.
    """
    venv = tmp_path / "stale-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / ".dev-install-complete").touch()
    if interpreter_shape == "dangling-symlink":
        (venv / "bin" / "python").symlink_to("/nonexistent/python3.13")

    arguments = ["dev", f"VENV={venv}"]
    if explicit_interpreter:
        arguments.append(f"PYTHON_BIN={sys.executable}")
    result = _run_make(*arguments)

    assert result.returncode != 0
    assert "make clean" in result.stderr


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
