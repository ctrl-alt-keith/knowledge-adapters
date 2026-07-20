import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pytest_temp_workspace_is_ignored() -> None:
    completed = subprocess.run(
        ["git", "check-ignore", "--quiet", "pytest-of-root/example/session.txt"],
        cwd=REPO_ROOT,
        check=False,
    )

    assert completed.returncode == 0
