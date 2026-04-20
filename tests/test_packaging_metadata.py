from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_exposes_installed_cli_entrypoint() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert pyproject["project"]["name"] == "knowledge-adapters"
    assert pyproject["project"]["scripts"] == {
        "knowledge-adapters": "knowledge_adapters.cli:main",
    }
