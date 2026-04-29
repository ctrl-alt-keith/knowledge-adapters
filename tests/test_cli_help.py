from __future__ import annotations

from pathlib import Path

from tests.cli_helpers import run_cli
from tests.cli_output_assertions import normalize_whitespace


def test_local_files_cli_help_includes_first_run_guidance(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "local_files", "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert "Normalize one existing UTF-8 text file into the shared artifact layout." in stdout
    assert "Empty UTF-8 files are allowed" in stdout
    assert "produce an empty content section." in stdout
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


def test_git_repo_cli_help_includes_filter_and_binary_guidance(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "git_repo", "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert "Clone or refresh a Git repository with system git" in stdout
    assert "Binary and non-UTF-8 files are skipped with explicit reporting." in stdout
    assert "File ordering is deterministic and lexical by repository path." in stdout
    assert "--repo-url REPO_URL" in stdout
    assert "--ref REF" in stdout
    assert "--include PATTERN" in stdout
    assert "--exclude PATTERN" in stdout
    assert "--subdir SUBDIR" in stdout
    assert "--dry-run" in stdout
    assert "knowledge-adapters git_repo" in stdout
    assert '--include "docs/**/*.md"' in stdout
    assert "--subdir docs" in stdout


def test_github_metadata_cli_help_includes_resource_type_guidance(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "github_metadata", "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert (
        "Fetch issues, pull requests, or releases from one GitHub or GitHub Enterprise repository"
        in stdout
    )
    assert "Issue mode filters out pull requests returned by the issues endpoint." in stdout
    assert "under issues/, pull_requests/, or releases/." in stdout
    assert "Issue comments can be included optionally in issue mode." in stdout
    assert "Pull request comments, release assets, changelog generation, timelines" in stdout
    assert "--repo OWNER/NAME" in stdout
    assert "--base-url BASE_URL" in stdout
    assert "--token-env ENV_VAR" in stdout
    assert "--output-dir DIR" in stdout
    assert "--resource-type {issue,pull_request,release}" in stdout
    assert "--state {open,closed,all}" in stdout
    assert "--since SINCE" in stdout
    assert "--max-items N" in stdout
    assert "--include-issue-comments" in stdout
    assert "--dry-run" in stdout
    assert "token value is read from the environment only and is never printed" in stdout
    assert "knowledge-adapters github_metadata" in stdout
