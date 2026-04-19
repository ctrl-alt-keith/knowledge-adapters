from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cli_path() -> Path:
    return _repo_root() / ".venv" / "bin" / "knowledge-adapters"


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cli_path = _cli_path()
    assert cli_path.exists()

    return subprocess.run(
        [str(cli_path), *args],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )


def test_local_files_cli_smoke_uses_installed_entrypoint_with_readme_style_args(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    source_file = notes_dir / "today.txt"
    source_file.write_text("Hello from smoke test.\n", encoding="utf-8")

    result = _run_cli(
        tmp_path,
        "local_files",
        "--file-path",
        "./notes/today.txt",
        "--output-dir",
        "./artifacts",
    )

    assert result.returncode == 0, result.stderr
    assert "Local files adapter invoked" in result.stdout
    assert "Wrote:" in result.stdout

    output_path = tmp_path / "artifacts" / "pages" / "today.md"
    assert output_path.read_text(encoding="utf-8") == (
        f"""# today.txt

## Metadata
- source: local_files
- canonical_id: {source_file.resolve()}
- parent_id:
- source_url: {source_file.resolve().as_uri()}
- fetched_at:
- updated_at:
- adapter: local_files

## Content

Hello from smoke test.
"""
    )

    payload = json.loads((tmp_path / "artifacts" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["files"] == [
        {
            "canonical_id": str(source_file.resolve()),
            "source_url": source_file.resolve().as_uri(),
            "output_path": "pages/today.md",
            "title": "today.txt",
        }
    ]


def test_confluence_cli_smoke_uses_installed_entrypoint_with_default_stub_client(
    tmp_path: Path,
) -> None:
    result = _run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
    )

    assert result.returncode == 0, result.stderr
    assert "Confluence adapter invoked" in result.stdout
    assert "Wrote:" in result.stdout

    output_path = tmp_path / "artifacts" / "pages" / "12345.md"
    assert output_path.read_text(encoding="utf-8") == (
        """# stub-page-12345

## Metadata
- source: confluence
- canonical_id: 12345
- parent_id:
- source_url: 
- fetched_at:
- updated_at:
- adapter: confluence

## Content

Stub content for page 12345.
"""
    )

    payload = json.loads((tmp_path / "artifacts" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["files"] == [
        {
            "canonical_id": "12345",
            "source_url": "",
            "output_path": "pages/12345.md",
            "title": "stub-page-12345",
        }
    ]
