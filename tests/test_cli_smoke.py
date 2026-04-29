from __future__ import annotations

import json
from pathlib import Path

from tests.cli_helpers import run_cli
from tests.cli_output_assertions import assert_contains_normalized, assert_write_summary


def test_top_level_help_introduces_shared_cli_flow(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--help")

    assert result.returncode == 0, result.stderr
    assert_contains_normalized(
        result.stdout,
        "Normalize knowledge sources into a shared local artifact layout.",
    )
    assert_contains_normalized(
        result.stdout,
        "plans a markdown artifact under pages/ plus manifest.json",
    )
    assert_contains_normalized(
        result.stdout,
        "Execute multiple configured adapter runs from one YAML file.",
    )
    assert_contains_normalized(
        result.stdout,
        "Normalize Confluence content into shared artifacts.",
    )
    assert_contains_normalized(
        result.stdout,
        "Normalize selected UTF-8 text files from a Git repository into shared artifacts.",
    )
    assert_contains_normalized(
        result.stdout,
        "Normalize GitHub issue, pull request, or release metadata from one repository "
        "into shared artifacts.",
    )
    assert_contains_normalized(
        result.stdout,
        "Normalize one local UTF-8 text file into shared artifacts.",
    )
    assert_contains_normalized(
        result.stdout,
        "Combine existing artifacts into one prompt-ready markdown file.",
    )
    assert_contains_normalized(
        result.stdout,
        "Start with --dry-run to preview the source, artifact path, manifest path,",
    )
    assert_contains_normalized(
        result.stdout,
        "Re-run without --dry-run to write the same artifact layout",
    )
    assert_contains_normalized(result.stdout, "knowledge-adapters run runs.yaml")
    assert_contains_normalized(result.stdout, "knowledge-adapters git_repo --help")
    assert_contains_normalized(result.stdout, "knowledge-adapters github_metadata --help")
    assert_contains_normalized(
        result.stdout,
        "knowledge-adapters bundle ./artifacts --output ./bundle.md",
    )


def test_local_files_cli_smoke_uses_installed_entrypoint_with_readme_style_args(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    source_file = notes_dir / "today.txt"
    source_file.write_text("Hello from smoke test.\n", encoding="utf-8")

    result = run_cli(
        tmp_path,
        "local_files",
        "--file-path",
        "./notes/today.txt",
        "--output-dir",
        "./artifacts",
    )

    assert result.returncode == 0, result.stderr
    assert "Local files adapter invoked" in result.stdout
    assert f"file_path: {source_file.resolve()}" in result.stdout
    assert f"output_dir: {(tmp_path / 'artifacts').resolve()}" in result.stdout
    assert "run_mode: write" in result.stdout
    assert "Plan: Local files run" in result.stdout
    assert f"resolved_file_path: {source_file.resolve()}" in result.stdout
    assert f"source_url: {source_file.resolve().as_uri()}" in result.stdout
    assert f"Artifact path: {tmp_path / 'artifacts' / 'pages' / 'today.md'}" in result.stdout
    assert "Wrote:" in result.stdout
    assert_write_summary(result.stdout, wrote=1, skipped=0)
    assert f"Artifact path: {tmp_path / 'artifacts' / 'pages' / 'today.md'}" in result.stdout
    assert f"Manifest path: {tmp_path / 'artifacts' / 'manifest.json'}" in result.stdout
    assert f"Write complete. Artifacts created under {tmp_path / 'artifacts'}" in result.stdout

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
