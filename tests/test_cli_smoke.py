from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.cli_output_assertions import (
    assert_contains_normalized,
    assert_write_summary,
    normalize_whitespace,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cli_command() -> list[str]:
    repo_local_cli = _repo_root() / ".venv" / "bin" / "knowledge-adapters"
    if repo_local_cli.exists():
        return [str(repo_local_cli)]

    return [sys.executable, "-m", "knowledge_adapters.cli"]


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_cli_command(), *args],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )


def test_top_level_help_introduces_shared_cli_flow(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert "Normalize knowledge sources into a shared local artifact layout." in stdout
    assert "plans a markdown artifact under pages/ plus manifest.json" in stdout
    assert "Normalize Confluence content into shared artifacts." in stdout
    assert "Normalize one local UTF-8 text file into shared artifacts." in stdout
    assert (
        "Start with --dry-run to preview the source, artifact path, manifest path,"
        in stdout
    )
    assert "Re-run without --dry-run to write the same artifact layout" in stdout


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
    assert "run_mode: write" in result.stdout
    assert "Plan: Local files run" in result.stdout
    assert f"resolved_file_path: {source_file.resolve()}" in result.stdout
    assert f"source_url: {source_file.resolve().as_uri()}" in result.stdout
    assert f"artifact_path: {tmp_path / 'artifacts' / 'pages' / 'today.md'}" in result.stdout
    assert "Wrote:" in result.stdout
    assert_write_summary(result.stdout, wrote=1, skipped=0)
    assert f"Artifact: {tmp_path / 'artifacts' / 'pages' / 'today.md'}" in result.stdout
    assert f"Manifest: {tmp_path / 'artifacts' / 'manifest.json'}" in result.stdout
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


def test_local_files_cli_help_includes_first_run_guidance(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "local_files", "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert (
        "Normalize one existing UTF-8 text file into the shared artifact layout."
        in stdout
    )
    assert "Empty UTF-8 files are allowed" in stdout
    assert "Files that are not valid UTF-8 text are rejected" in stdout
    assert "directories are not supported" in stdout
    assert "--file-path FILE" in stdout
    assert "Path to the one existing local UTF-8 text file for this run." in stdout
    assert "Empty files are allowed; directories are not supported." in stdout
    assert "Relative paths" in stdout
    assert "resolve from the cwd." in stdout
    assert "--output-dir DIR" in stdout
    assert "Directory where pages/ and manifest.json are written." in stdout
    assert "local_files handles one file per run and always plans one write;" in stdout
    assert "it does not use manifest-based skip logic." in stdout
    assert "resolved file path, artifact path, manifest path" in stdout
    assert "without writing files." in stdout
    assert "knowledge-adapters local_files" in stdout
    assert "--dry-run" in stdout


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
    assert "client_mode: stub" in result.stdout
    assert "content_source: scaffolded page content" in result.stdout
    assert "fetch_scope: page" in result.stdout
    assert "run_mode: write" in result.stdout
    assert "Plan: Confluence run" in result.stdout
    assert "resolved_page_id: 12345" in result.stdout
    assert "artifact_path:" in result.stdout
    assert "auth_method:" not in result.stdout
    assert "Wrote:" in result.stdout
    assert_write_summary(result.stdout, wrote=1, skipped=0)
    assert "Manifest:" in result.stdout
    assert f"Write complete. Artifacts created under {tmp_path / 'artifacts'}" in result.stdout

    output_path = tmp_path / "artifacts" / "pages" / "12345.md"
    assert output_path.read_text(encoding="utf-8") == (
        """# stub-page-12345

## Metadata
- source: confluence
- canonical_id: 12345
- parent_id:
- source_url: https://example.com/wiki/pages/viewpage.action?pageId=12345
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
            "source_url": "https://example.com/wiki/pages/viewpage.action?pageId=12345",
            "output_path": "pages/12345.md",
            "title": "stub-page-12345",
        }
    ]


def test_confluence_help_lists_supported_auth_methods_and_examples(
    tmp_path: Path,
) -> None:
    result = _run_cli(
        tmp_path,
        "confluence",
        "--help",
    )
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0
    assert "CONFLUENCE_BEARER_TOKEN" in stdout
    assert "CONFLUENCE_CLIENT_CERT_FILE" in stdout
    assert "client-cert-env" in stdout
    assert "--debug" in stdout
    assert "request debug details" in stdout
    assert "artifact layout and reporting" in stdout
    assert "page or, with --tree, a page tree" in stdout
    assert "planned artifact paths, manifest path, and write/skip decisions" in stdout
    assert_contains_normalized(stdout, "In tree mode, dry-run previews the root page and")
    assert "artifact paths used in write mode" in stdout
    assert "same resolve, plan, and write flow" in stdout
    assert "'real' fetches from" in stdout
    assert "using --auth-method" in stdout
    assert "contract-tested live fetches" in stdout
    assert "The CLI resolves either input into one canonical page" in stdout
    assert "source URL for artifact and manifest reporting" in stdout
    assert "artifact and manifest reporting" in stdout
    assert "Traverse the resolved root page and discovered" in stdout
    assert "descendants instead of only one page." in stdout
    assert "Maximum descendant depth for --tree." in stdout
    assert "Ignored unless --tree is set." in stdout
    assert "CONFLUENCE_BEARER_TOKEN=... knowledge-adapters confluence" in stdout
    assert "--max-depth 1" in stdout
    assert "--dry-run" in stdout
