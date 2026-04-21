from __future__ import annotations

import json
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

    assert result.returncode == 0, result.stderr
    assert "Normalize knowledge sources into a shared local artifact layout." in result.stdout
    assert "plans a markdown artifact under pages/ plus manifest.json" in result.stdout
    assert "Normalize Confluence content into shared artifacts." in result.stdout
    assert "Normalize a local text file into shared artifacts." in result.stdout
    assert (
        "Start with --dry-run to preview the source, artifact path, manifest path,"
        in result.stdout
    )
    assert "Re-run without --dry-run to write the same artifact layout" in result.stdout


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
    assert "Summary: wrote 1, skipped 0" in result.stdout
    assert "Manifest:" in result.stdout

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

    assert result.returncode == 0, result.stderr
    assert (
        "Normalize one existing UTF-8 text file into the shared artifact layout."
        in result.stdout
    )
    assert "Empty UTF-8 files are allowed" in result.stdout
    assert "Files that are not valid UTF-8 text are rejected." in result.stdout
    assert "Directories are not supported." in result.stdout
    assert "--file-path FILE" in result.stdout
    assert "Path to one existing local UTF-8 text file." in result.stdout
    assert "Empty files" in result.stdout
    assert "are allowed; directories are not supported." in result.stdout
    assert "directories are not supported." in result.stdout
    assert "Relative paths" in result.stdout
    assert "resolve from the cwd." in result.stdout
    assert "--output-dir DIR" in result.stdout
    assert "Directory where pages/ and manifest.json are written." in result.stdout
    assert "resolved file path, artifact path, manifest path" in result.stdout
    assert "without writing files." in result.stdout
    assert "knowledge-adapters local_files" in result.stdout
    assert "--dry-run" in result.stdout


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
    assert "Summary: wrote 1, skipped 0" in result.stdout
    assert "Manifest:" in result.stdout

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

    assert result.returncode == 0
    assert "CONFLUENCE_BEARER_TOKEN" in result.stdout
    assert "CONFLUENCE_CLIENT_CERT_FILE" in result.stdout
    assert "client-cert-env" in result.stdout
    assert "--debug" in result.stdout
    assert "request debug details" in result.stdout
    assert "artifact layout and reporting" in result.stdout
    assert "page or, with --tree, a page tree" in result.stdout
    assert "planned artifact paths, manifest path, and write/skip decisions" in result.stdout
    assert "In tree mode, dry-run previews the root page plus" in result.stdout
    assert "artifact paths that write mode would use" in result.stdout
    assert "same resolve, plan, and write flow" in result.stdout
    assert "'real' fetches from" in result.stdout
    assert "using --auth-method" in result.stdout
    assert "contract-tested live fetches" in result.stdout
    assert "The CLI resolves either input into one canonical page" in result.stdout
    assert "source URL for artifact and manifest reporting" in result.stdout
    assert "artifact and manifest reporting" in result.stdout
    assert "Traverse the resolved root page plus discovered" in result.stdout
    assert "descendants instead of only one page." in result.stdout
    assert "Maximum descendant depth for --tree." in result.stdout
    assert "Ignored unless --tree is set." in result.stdout
    assert "CONFLUENCE_BEARER_TOKEN=... knowledge-adapters confluence" in result.stdout
    assert "--max-depth 1" in result.stdout
    assert "--dry-run" in result.stdout
