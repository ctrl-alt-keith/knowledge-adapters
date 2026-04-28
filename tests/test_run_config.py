from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from pytest import CaptureFixture, MonkeyPatch

import knowledge_adapters.cli as cli
from knowledge_adapters.cli import main
from knowledge_adapters.confluence.models import ResolvedTarget
from knowledge_adapters.run_config import (
    ConfiguredBundle,
    ConfiguredRun,
    load_run_config,
    select_bundle,
    select_runs,
)


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _patch_large_real_confluence_tree(monkeypatch: MonkeyPatch) -> None:
    from knowledge_adapters.confluence import client as client_module

    pages = {
        str(page_id): {
            "canonical_id": str(page_id),
            "title": f"Page {page_id}",
            "source_url": f"https://example.com/wiki/pages/{page_id}",
            "content": f"Content for {page_id}.",
            "page_version": page_id,
            "last_modified": "2026-04-20T00:00:00Z",
        }
        for page_id in range(100, 1101)
    }
    children_by_parent: dict[str, list[str]] = {
        "100": [str(page_id) for page_id in range(101, 1101)],
    }
    children_by_parent.update({str(page_id): [] for page_id in range(101, 1101)})

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str,
        auth_method: str,
        ca_bundle: str | None = None,
        no_ca_bundle: bool = False,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, no_ca_bundle, client_cert_file, client_key_file
        return dict(pages[str(target.page_id)])

    def stub_child_id_discovery(
        target: ResolvedTarget,
        *,
        base_url: str,
        auth_method: str,
        ca_bundle: str | None = None,
        no_ca_bundle: bool = False,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
        progress_callback: Any = None,
    ) -> list[str]:
        del (
            base_url,
            auth_method,
            ca_bundle,
            no_ca_bundle,
            client_cert_file,
            client_key_file,
            progress_callback,
        )
        return children_by_parent[str(target.page_id)]

    def fail_if_stub_used(target: ResolvedTarget) -> dict[str, object]:
        raise AssertionError(
            f"stub client should not be used in real traversal mode for {target.page_id}"
        )

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        stub_child_id_discovery,
        raising=False,
    )
    monkeypatch.setattr(client_module, "fetch_page", fail_if_stub_used)


def _write_large_real_tree_run_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-tree
    type: confluence
    client_mode: real
    base_url: https://example.com/wiki
    target: "100"
    output_dir: ./artifacts/confluence/docs-tree
    tree: true
    max_depth: 1
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path


def test_load_run_config_resolves_relative_paths_from_config_location(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    fetch_cache_dir: ./.cache/confluence-fetches
    tree_cache_dir: ./.cache/confluence-tree
    force_refresh: true
    clear_cache: true
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.config_path == config_path.resolve()
    assert run_config.runs == (
        ConfiguredRun(
            name="docs-home",
            run_type="confluence",
            argv=(
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str((tmp_path / "artifacts" / "confluence" / "docs-home").resolve()),
                "--fetch-cache-dir",
                str((tmp_path / ".cache" / "confluence-fetches").resolve()),
                "--tree-cache-dir",
                str((tmp_path / ".cache" / "confluence-tree").resolve()),
                "--force-refresh",
                "--clear-cache",
            ),
            dry_run=False,
        ),
        ConfiguredRun(
            name="team-notes",
            run_type="local_files",
            argv=(
                "local_files",
                "--file-path",
                str((tmp_path / "inputs" / "team-notes.txt").resolve()),
                "--output-dir",
                str((tmp_path / "artifacts" / "local" / "team-notes").resolve()),
                "--dry-run",
            ),
            dry_run=True,
        ),
    )


def test_load_run_config_supports_bundle_stale_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: stale-review-bundle
    type: bundle
    inputs:
      - ./artifacts/confluence/docs-tree
    output: ./bundles/docs-tree.md
    stale_mode: flag
    header_mode: minimal
    include:
      - "pages/*"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="stale-review-bundle",
            run_type="bundle",
            argv=(
                "bundle",
                str((tmp_path / "artifacts" / "confluence" / "docs-tree").resolve()),
                "--output",
                str((tmp_path / "bundles" / "docs-tree.md").resolve()),
                "--header-mode",
                "minimal",
                "--stale-mode",
                "flag",
                "--include",
                "pages/*",
            ),
            dry_run=False,
        ),
    )


def test_load_run_config_supports_named_bundle_referencing_one_run(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    baseline_manifest = tmp_path / "baseline" / "manifest.json"
    config_path.write_text(
        f"""
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
bundles:
  - name: review-pack
    runs: team-notes
    output: ./bundles/review-pack.md
    max_bytes: 250000
    order: input
    header_mode: minimal
    include:
      - "team-*"
    exclude:
      - "*draft*"
    changed_only: true
    baseline_manifest: {baseline_manifest}
    stale_mode: flag
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.bundles == (
        ConfiguredBundle(
            name="review-pack",
            inputs=(str((tmp_path / "artifacts" / "local" / "team-notes").resolve()),),
            output=str((tmp_path / "bundles" / "review-pack.md").resolve()),
            max_bytes=250000,
            order="input",
            header_mode="minimal",
            include_patterns=("team-*",),
            exclude_patterns=("*draft*",),
            changed_only=True,
            baseline_manifest=str(baseline_manifest),
            stale_mode="flag",
        ),
    )


def test_load_run_config_supports_named_bundle_referencing_multiple_runs(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-tree
bundles:
  - name: merged-review
    runs:
      - team-notes
      - docs-tree
    output: ./bundles/merged-review.md
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.bundles == (
        ConfiguredBundle(
            name="merged-review",
            inputs=(
                str((tmp_path / "artifacts" / "local" / "team-notes").resolve()),
                str((tmp_path / "artifacts" / "confluence" / "docs-tree").resolve()),
            ),
            output=str((tmp_path / "bundles" / "merged-review.md").resolve()),
        ),
    )


def test_load_run_config_rejects_unknown_named_bundle_run_reference(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
bundles:
  - name: review-pack
    runs:
      - team-notes
      - missing-run
    output: ./bundles/review-pack.md
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="references unknown run name 'missing-run'"):
        load_run_config(config_path)


def test_load_run_config_supports_git_repo_filters_and_ref(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        f"""
runs:
  - name: repo-docs
    type: git_repo
    repo_url: {repo_dir}
    ref: v1.2.3
    include:
      - docs/**/*.md
      - README.md
    exclude:
      - docs/archive/*
    subdir: docs
    output_dir: ./artifacts/git/repo-docs
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="repo-docs",
            run_type="git_repo",
            argv=(
                "git_repo",
                "--repo-url",
                str(repo_dir),
                "--output-dir",
                str((tmp_path / "artifacts" / "git" / "repo-docs").resolve()),
                "--ref",
                "v1.2.3",
                "--subdir",
                "docs",
                "--include",
                "docs/**/*.md",
                "--include",
                "README.md",
                "--exclude",
                "docs/archive/*",
                "--dry-run",
            ),
            dry_run=True,
        ),
    )


def test_load_run_config_supports_github_metadata_inputs(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: repo-issues
    type: github_metadata
    repo: octo/project
    resource_type: pull_request
    base_url: https://github.example.com/api/v3
    token_env: GH_TOKEN
    state: all
    since: 2026-01-01T00:00:00Z
    max_items: 25
    include_issue_comments: true
    output_dir: ./artifacts/github/repo-issues
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="repo-issues",
            run_type="github_metadata",
            argv=(
                "github_metadata",
                "--repo",
                "octo/project",
                "--token-env",
                "GH_TOKEN",
                "--output-dir",
                str((tmp_path / "artifacts" / "github" / "repo-issues").resolve()),
                "--resource-type",
                "pull_request",
                "--base-url",
                "https://github.example.com/api/v3",
                "--state",
                "all",
                "--since",
                "2026-01-01T00:00:00Z",
                "--max-items",
                "25",
                "--include-issue-comments",
                "--dry-run",
            ),
            dry_run=True,
        ),
    )


def test_load_run_config_supports_github_metadata_release_resource_type(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: repo-releases
    type: github_metadata
    repo: octo/project
    resource_type: release
    token_env: GH_TOKEN
    since: 2026-01-01T00:00:00Z
    max_items: 10
    output_dir: ./artifacts/github/repo-releases
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="repo-releases",
            run_type="github_metadata",
            argv=(
                "github_metadata",
                "--repo",
                "octo/project",
                "--token-env",
                "GH_TOKEN",
                "--output-dir",
                str((tmp_path / "artifacts" / "github" / "repo-releases").resolve()),
                "--resource-type",
                "release",
                "--since",
                "2026-01-01T00:00:00Z",
                "--max-items",
                "10",
            ),
            dry_run=False,
        ),
    )


@pytest.mark.parametrize(
    ("field_block", "expected_fragment"),
    [
        ("state: merged", "unsupported 'state' value"),
        ("resource_type: milestone", "unsupported 'resource_type' value"),
        ("max_items: 0", "'max_items' to a positive integer"),
    ],
)
def test_load_run_config_rejects_invalid_github_metadata_values(
    tmp_path: Path,
    field_block: str,
    expected_fragment: str,
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        f"""
runs:
  - name: repo-issues
    type: github_metadata
    repo: octo/project
    token_env: GH_TOKEN
    output_dir: ./artifacts/github/repo-issues
    {field_block}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=expected_fragment):
        load_run_config(config_path)


def test_load_run_config_rejects_invalid_git_repo_pattern_values(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: repo-docs
    type: git_repo
    repo_url: https://github.com/example/project.git
    include:
      - docs/**/*.md
      - ""
    output_dir: ./artifacts/git/repo-docs
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must define 'include' as a non-empty string or list"):
        load_run_config(config_path)


@pytest.mark.parametrize(
    ("space_block", "expected_arg"),
    [
        ("space_key: ENG", ("--space-key", "ENG")),
        (
            "space_url: https://example.com/wiki/spaces/ENG/overview",
            ("--space-url", "https://example.com/wiki/spaces/ENG/overview"),
        ),
    ],
)
def test_load_run_config_supports_confluence_space_mode(
    tmp_path: Path,
    space_block: str,
    expected_arg: tuple[str, str],
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        f"""
runs:
  - name: docs-space
    type: confluence
    base_url: https://example.com/wiki
    {space_block}
    output_dir: ./artifacts/confluence/docs-space
    client_mode: real
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="docs-space",
            run_type="confluence",
            argv=(
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                *expected_arg,
                "--output-dir",
                str((tmp_path / "artifacts" / "confluence" / "docs-space").resolve()),
                "--client-mode",
                "real",
            ),
            dry_run=False,
        ),
    )


@pytest.mark.parametrize(
    ("extra_block", "expected_fragment"),
    [
        ("target: '12345'", "cannot combine space mode with 'target'"),
        ("tree: true", "cannot combine space mode with 'tree'"),
        ("max_depth: 1", "cannot combine space mode with 'max_depth'"),
        ("client_mode: stub", "space mode requires --client-mode real"),
        ("space_url: https://example.com/wiki/spaces/ENG/overview", "only one"),
    ],
)
def test_load_run_config_rejects_invalid_confluence_space_mode_combinations(
    tmp_path: Path,
    extra_block: str,
    expected_fragment: str,
) -> None:
    config_path = tmp_path / "runs.yaml"
    client_mode_block = "" if "client_mode" in extra_block else "    client_mode: real\n"
    config_path.write_text(
        f"""
runs:
  - name: docs-space
    type: confluence
    base_url: https://example.com/wiki
    space_key: ENG
    output_dir: ./artifacts/confluence/docs-space
{client_mode_block}    {extra_block}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=expected_fragment):
        load_run_config(config_path)


def test_load_run_config_rejects_unsupported_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./notes.txt
    output_dir: ./artifacts
    unexpected: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported keys"):
        load_run_config(config_path)


def test_load_run_config_parses_enabled_flag(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./notes.txt
    output_dir: ./artifacts
    enabled: false
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="team-notes",
            run_type="local_files",
            argv=(
                "local_files",
                "--file-path",
                str((tmp_path / "notes.txt").resolve()),
                "--output-dir",
                str((tmp_path / "artifacts").resolve()),
            ),
            dry_run=False,
            enabled=False,
        ),
    )


def test_select_runs_skips_disabled_runs_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    enabled: false
  - name: team-notes
    type: local_files
    file_path: ./notes.txt
    output_dir: ./artifacts/local/team-notes
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "67890"
    output_dir: ./artifacts/confluence/docs-tree
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert tuple(run.name for run in select_runs(run_config)) == ("team-notes", "docs-tree")


def test_select_runs_only_named_runs_preserves_config_order_and_overrides_disabled(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    enabled: false
  - name: team-notes
    type: local_files
    file_path: ./notes.txt
    output_dir: ./artifacts/local/team-notes
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "67890"
    output_dir: ./artifacts/confluence/docs-tree
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert tuple(
        run.name for run in select_runs(run_config, only_names=("docs-tree", "docs-home"))
    ) == (
        "docs-home",
        "docs-tree",
    )


def test_select_runs_rejects_unknown_only_names(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./notes.txt
    output_dir: ./artifacts
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    with pytest.raises(ValueError, match="Unknown run name\\(s\\) for --only"):
        select_runs(run_config, only_names=("missing-run",))


def test_select_bundle_rejects_unknown_named_bundle(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./notes.txt
    output_dir: ./artifacts
bundles:
  - name: review-pack
    runs: team-notes
    output: ./bundles/review-pack.md
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    with pytest.raises(ValueError, match="Unknown bundle name 'missing-bundle'"):
        select_bundle(run_config, name="missing-bundle")


@pytest.mark.parametrize(
    ("field_name", "field_block", "expected_fragment"),
    [
        (
            "client_mode",
            "client_mode: preview",
            "unsupported 'client_mode' value 'preview'",
        ),
        (
            "auth_method",
            "auth_method: oauth",
            "unsupported 'auth_method' value 'oauth'",
        ),
    ],
)
def test_load_run_config_rejects_invalid_confluence_enum_values(
    tmp_path: Path,
    field_name: str,
    field_block: str,
    expected_fragment: str,
) -> None:
    del field_name
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        f"""
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    {field_block}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=expected_fragment):
        load_run_config(config_path)


def test_load_run_config_rejects_invalid_confluence_target_before_execution(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: https://other.example.com/wiki/pages/viewpage.action?pageId=12345
    output_dir: ./artifacts/confluence/docs-home
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="has invalid 'target'"):
        load_run_config(config_path)


def test_load_run_config_rejects_negative_confluence_max_depth(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-tree
    tree: true
    max_depth: -1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="'max_depth'"):
        load_run_config(config_path)


def test_run_command_executes_multiple_runs_in_sequence(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Config-driven run invoked" in captured.out
    assert "Run 1/2 started: team-notes (local_files)" in captured.out
    assert "Run 1/2 completed: team-notes (local_files)" in captured.out
    assert "Run 2/2 started: docs-home (confluence)" in captured.out
    assert "Run 2/2 completed: docs-home (confluence)" in captured.out
    assert captured.out.index("Run 1/2 started: team-notes (local_files)") < captured.out.index(
        "Run 2/2 started: docs-home (confluence)"
    )
    assert "Run summary: wrote 1, skipped 0" in captured.out
    assert "Aggregate summary:" in captured.out
    assert "runs_completed: 2" in captured.out
    assert "write_runs: 2" in captured.out
    assert "dry_run_runs: 0" in captured.out
    assert "wrote: 2" in captured.out
    assert "skipped: 0" in captured.out

    local_output_dir = tmp_path / "artifacts" / "local" / "team-notes"
    local_output_path = local_output_dir / "pages" / "team-notes.md"
    assert local_output_path.exists()
    assert "Ship it." in local_output_path.read_text(encoding="utf-8")
    local_manifest = json.loads((local_output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert local_manifest["files"] == [
        {
            "canonical_id": str(source_file.resolve()),
            "source_url": source_file.resolve().as_uri(),
            "output_path": "pages/team-notes.md",
            "title": "team-notes.txt",
        }
    ]

    confluence_output_dir = tmp_path / "artifacts" / "confluence" / "docs-home"
    confluence_output_path = confluence_output_dir / "pages" / "12345.md"
    assert confluence_output_path.exists()
    assert "Stub content for page 12345." in confluence_output_path.read_text(encoding="utf-8")
    confluence_manifest = json.loads(
        (confluence_output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert confluence_manifest["files"] == [
        {
            "canonical_id": "12345",
            "source_url": "https://example.com/wiki/pages/viewpage.action?pageId=12345",
            "output_path": "pages/12345.md",
            "title": "stub-page-12345",
            "page_version": 1,
            "last_modified": "1970-01-01T00:00:00Z",
        }
    ]


def test_run_command_preserves_nested_confluence_inline_progress_on_tty(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    _patch_large_real_confluence_tree(monkeypatch)
    config_path = _write_large_real_tree_run_config(tmp_path)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert output.count("\rdiscovered_pages: ") == 3
    assert "\rTree progress: depth 0, discovered 1, fetched 1, planned 1" in output
    assert "\rTree progress: depth 1, discovered 1001, fetched 1001, planned 1001" in output
    assert output.rfind("\rdiscovered_pages: 1001") < output.rfind(
        "\rTree progress: depth 1, discovered 1001, fetched 1001, planned 1001"
    )
    assert "\rdiscovered_pages: 500\n" not in output
    assert "\rdiscovered_pages: 1000\n" not in output
    assert "\rdiscovered_pages: 1001\n" not in output
    assert (
        "\rTree progress: depth 1, discovered 1001, fetched 1001, planned 1001\n"
        "Confluence adapter invoked"
        in output
    )
    assert "Run 1/1 completed: docs-tree (confluence)" in output
    assert "Run summary: would write 1001, would skip 0" in output
    assert "Aggregate summary:" in output
    assert "dry_run_runs: 1" in output
    assert "would_write: 1001" in output
    assert "would_skip: 0" in output


def test_run_command_keeps_nested_confluence_progress_line_based_without_tty(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    _patch_large_real_confluence_tree(monkeypatch)
    config_path = _write_large_real_tree_run_config(tmp_path)

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "\r" not in output
    assert "discovered_pages: 500\ndiscovered_pages: 1000\n" in output
    assert "Run 1/1 completed: docs-tree (confluence)" in output
    assert "Run summary: would write 1001, would skip 0" in output
    assert "would_write: 1001" in output
    assert "would_skip: 0" in output


def test_run_command_executes_explicit_input_bundle_run(tmp_path: Path) -> None:
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
  - name: team-notes-bundle
    type: bundle
    inputs:
      - ./artifacts/local/team-notes
    output: ./bundles/team-notes.md
    header_mode: minimal
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    bundle_path = tmp_path / "bundles" / "team-notes.md"
    assert bundle_path.exists()
    assert "## team-notes.txt" in bundle_path.read_text(encoding="utf-8")
    assert "Ship it." in bundle_path.read_text(encoding="utf-8")


def test_run_command_skips_disabled_runs_by_default(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    enabled: false
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "runs_skipped_disabled: 1" in captured.out
    assert "skipped_disabled: docs-home (confluence)" in captured.out
    assert "Run 1/1 started: team-notes (local_files)" in captured.out
    assert "Run 1/1 started: docs-home (confluence)" not in captured.out
    assert "runs_completed: 1" in captured.out

    local_output_path = tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "team-notes.md"
    assert local_output_path.exists()
    disabled_output_path = (
        tmp_path / "artifacts" / "confluence" / "docs-home" / "pages" / "12345.md"
    )
    assert not disabled_output_path.exists()


def test_run_command_only_runs_selected_names_in_config_order_and_overrides_disabled(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    enabled: false
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "67890"
    output_dir: ./artifacts/confluence/docs-tree
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path), "--only", "docs-tree,docs-home"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "only: docs-tree, docs-home" in captured.out
    assert "runs_selected: 2" in captured.out
    assert "runs_skipped_disabled: 0" in captured.out
    assert "Run 1/2 started: docs-home (confluence)" in captured.out
    assert "Run 2/2 started: docs-tree (confluence)" in captured.out
    assert "Run 1/2 started: team-notes (local_files)" not in captured.out

    disabled_output_path = (
        tmp_path / "artifacts" / "confluence" / "docs-home" / "pages" / "12345.md"
    )
    assert disabled_output_path.exists()
    non_selected_output_path = (
        tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "team-notes.md"
    )
    assert not non_selected_output_path.exists()


def test_run_command_reports_dry_run_counts(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-tree
    tree: true
    max_depth: 1
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Run summary: would write 1, would skip 0" in captured.out
    assert "Aggregate summary:" in captured.out
    assert "write_runs: 0" in captured.out
    assert "dry_run_runs: 1" in captured.out
    assert "would_write: 1" in captured.out
    assert "would_skip: 0" in captured.out
    assert "pages/12345.md" not in captured.out
    assert not (tmp_path / "artifacts").exists()


def test_run_command_verbose_preserves_nested_confluence_per_item_output(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-tree
    tree: true
    max_depth: 1
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", "--verbose", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Run summary: would write 1, would skip 0" in captured.out
    assert (
        f"would write {tmp_path / 'artifacts' / 'confluence' / 'docs-tree' / 'pages' / '12345.md'}"
        in captured.out
    )


def test_run_command_preserves_nested_adapter_error_details(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CONFLUENCE_BEARER_TOKEN", raising=False)
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    client_mode: real
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(config_path)])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Config-driven run invoked" in captured.out
    assert f"config_path: {config_path.resolve()}" in captured.out
    assert "runs_in_config: 1" in captured.out
    assert "Run 1/1 started: docs-home (confluence)" in captured.out
    assert "Run 1/1 failed: docs-home (confluence)" in captured.out
    assert (
        "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while "
        "executing knowledge-adapters confluence --base-url https://example.com/wiki "
        "--target 12345 --output-dir "
    ) in captured.err
    assert (
        "Missing Confluence bearer token. Set CONFLUENCE_BEARER_TOKEN for "
        "--client-mode real --auth-method bearer-env."
    ) in captured.err


def test_run_command_stops_on_first_failed_run_by_default(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CONFLUENCE_BEARER_TOKEN", raising=False)
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    client_mode: real
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(config_path)])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Run 1/2 started: docs-home (confluence)" in captured.out
    assert "Run 1/2 failed: docs-home (confluence)" in captured.out
    assert "Run 2/2 started: team-notes (local_files)" not in captured.out
    assert "Aggregate summary:" not in captured.out
    assert "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while " in (
        captured.err
    )
    assert "Missing Confluence bearer token." in captured.err
    assert not (tmp_path / "artifacts" / "local" / "team-notes").exists()


def test_run_command_continue_on_error_executes_later_runs_and_reports_failures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CONFLUENCE_BEARER_TOKEN", raising=False)
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    client_mode: real
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path), "--continue-on-error"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Run 1/2 started: docs-home (confluence)" in captured.out
    assert "Run 1/2 failed: docs-home (confluence)" in captured.out
    assert "Run 2/2 started: team-notes (local_files)" in captured.out
    assert "Run 2/2 completed: team-notes (local_files)" in captured.out
    assert "Aggregate summary:" in captured.out
    assert "runs_completed: 1" in captured.out
    assert "runs_failed: 1" in captured.out
    assert "write_runs: 1" in captured.out
    assert "dry_run_runs: 0" in captured.out
    assert "wrote: 1" in captured.out
    assert "skipped: 0" in captured.out
    assert "Config run completed with failures." in captured.out
    assert "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while " in (
        captured.err
    )
    assert "Missing Confluence bearer token." in captured.err

    local_output_path = tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "team-notes.md"
    assert local_output_path.exists()
    assert "Ship it." in local_output_path.read_text(encoding="utf-8")


def test_run_command_keyboard_interrupt_skips_current_run_and_continues(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    first_source = tmp_path / "inputs" / "first.txt"
    second_source = tmp_path / "inputs" / "second.txt"
    first_source.parent.mkdir(parents=True)
    first_source.write_text("First file.\n", encoding="utf-8")
    second_source.write_text("Second file.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: first-run
    type: local_files
    file_path: ./inputs/first.txt
    output_dir: ./artifacts/local/first-run
  - name: second-run
    type: local_files
    file_path: ./inputs/second.txt
    output_dir: ./artifacts/local/second-run
""".strip()
        + "\n",
        encoding="utf-8",
    )

    real_execute_configured_run = cli._execute_configured_run
    attempt_count = 0

    def interrupt_once(
        argv: tuple[str, ...],
        *,
        captured_stdout: Any,
        captured_stderr: Any,
    ) -> int:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise KeyboardInterrupt
        return real_execute_configured_run(
            argv,
            captured_stdout=captured_stdout,
            captured_stderr=captured_stderr,
        )

    monkeypatch.setattr(cli, "_execute_configured_run", interrupt_once)

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    assert attempt_count == 2
    captured = capsys.readouterr()
    assert "Run 1/2 started: first-run (local_files)" in captured.out
    assert "Run 1/2 interrupted: first-run (local_files)" in captured.out
    assert "Run interrupted: skipping remaining work for this run" in captured.out
    assert "Run summary: interrupted, skipped remaining work for this run" in captured.out
    assert "Run 2/2 started: second-run (local_files)" in captured.out
    assert "Run 2/2 completed: second-run (local_files)" in captured.out
    assert "Aggregate summary:" in captured.out
    assert "runs_completed: 1" in captured.out
    assert "runs_failed: 0" in captured.out
    assert "runs_interrupted: 1" in captured.out
    assert "write_runs: 1" in captured.out
    assert "dry_run_runs: 0" in captured.out
    assert "wrote: 1" in captured.out
    assert "skipped: 0" in captured.out
    assert "Config run complete. Processed 1 completed run(s) and 1 interrupted run(s)" in (
        captured.out
    )

    assert not (tmp_path / "artifacts" / "local" / "first-run").exists()
    second_output_path = tmp_path / "artifacts" / "local" / "second-run" / "pages" / "second.md"
    assert second_output_path.exists()
    assert "Second file." in second_output_path.read_text(encoding="utf-8")


def test_run_command_second_keyboard_interrupt_propagates_immediately(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: first-run
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/first-run
  - name: second-run
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/second-run
""".strip()
        + "\n",
        encoding="utf-8",
    )

    attempt_count = 0

    def always_interrupt(
        argv: tuple[str, ...],
        *,
        captured_stdout: Any,
        captured_stderr: Any,
    ) -> int:
        del argv, captured_stdout, captured_stderr
        nonlocal attempt_count
        attempt_count += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_execute_configured_run", always_interrupt)

    with pytest.raises(KeyboardInterrupt):
        main(["run", str(config_path)])

    assert attempt_count == 2
    captured = capsys.readouterr()
    assert "Run 1/2 started: first-run (local_files)" in captured.out
    assert "Run 1/2 interrupted: first-run (local_files)" in captured.out
    assert "Run interrupted: skipping remaining work for this run" in captured.out
    assert "Run 2/2 started: second-run (local_files)" in captured.out
    assert "Run 2/2 interrupted: second-run (local_files)" not in captured.out
    assert "Aggregate summary:" not in captured.out


def test_load_run_config_includes_confluence_tls_and_client_cert_paths(tmp_path: Path) -> None:
    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    (certs_dir / "internal-ca.pem").write_text("ca\n", encoding="utf-8")
    (certs_dir / "confluence-client.crt").write_text("cert\n", encoding="utf-8")
    (certs_dir / "confluence-client.key").write_text("key\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/internal-ca.pem
    client_cert_file: ./certs/confluence-client.crt
    client_key_file: ./certs/confluence-client.key
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="docs-home",
            run_type="confluence",
            argv=(
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str((tmp_path / "artifacts" / "confluence" / "docs-home").resolve()),
                "--ca-bundle",
                str((tmp_path / "certs" / "internal-ca.pem").resolve()),
                "--client-cert-file",
                str((tmp_path / "certs" / "confluence-client.crt").resolve()),
                "--client-key-file",
                str((tmp_path / "certs" / "confluence-client.key").resolve()),
            ),
            dry_run=False,
        ),
    )


def test_load_run_config_env_ca_bundle_overrides_confluence_config_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    (certs_dir / "config-ca.pem").write_text("config ca\n", encoding="utf-8")
    env_ca_bundle = tmp_path / "env-ca.pem"
    env_ca_bundle.write_text("env ca\n", encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGE_ADAPTERS_CONFLUENCE_CA_BUNDLE", str(env_ca_bundle))
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/config-ca.pem
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert "--ca-bundle" in run_config.runs[0].argv
    assert str(env_ca_bundle) in run_config.runs[0].argv
    assert str((certs_dir / "config-ca.pem").resolve()) not in run_config.runs[0].argv


def test_load_run_config_empty_env_ca_bundle_disables_confluence_config_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_ADAPTERS_CONFLUENCE_CA_BUNDLE", "")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/missing-ca.pem
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert "--ca-bundle" not in run_config.runs[0].argv


def test_load_run_config_no_ca_bundle_flag_disables_env_and_config_ca_bundle(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    env_ca_bundle = tmp_path / "env-ca.pem"
    env_ca_bundle.write_text("env ca\n", encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGE_ADAPTERS_CONFLUENCE_CA_BUNDLE", str(env_ca_bundle))
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/missing-ca.pem
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path, no_confluence_ca_bundle=True)

    assert "--ca-bundle" not in run_config.runs[0].argv
    assert "--no-ca-bundle" in run_config.runs[0].argv


def test_run_command_no_ca_bundle_flag_disables_env_and_config_ca_bundle(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from knowledge_adapters.confluence import client as client_module

    observed_kwargs: list[dict[str, object]] = []

    def stub_real_fetch(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        observed_kwargs.append(dict(kwargs))
        return {
            "canonical_id": "12345",
            "title": "Real Page",
            "content": "<p>Hello from Confluence.</p>",
            "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
            "page_version": 7,
            "last_modified": "2026-04-20T12:34:56Z",
        }

    env_ca_bundle = tmp_path / "env-ca.pem"
    env_ca_bundle.write_text("env ca\n", encoding="utf-8")
    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setenv("KNOWLEDGE_ADAPTERS_CONFLUENCE_CA_BUNDLE", str(env_ca_bundle))
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    client_mode: real
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/missing-ca.pem
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", "--no-ca-bundle", str(config_path)])

    assert exit_code == 0
    assert observed_kwargs == [
        {
            "base_url": "https://example.com/wiki",
            "auth_method": "bearer-env",
            "ca_bundle": None,
            "client_cert_file": None,
            "client_key_file": None,
            "no_ca_bundle": True,
        }
    ]


def test_load_run_config_rejects_confluence_client_key_without_client_cert(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    client_key_file: ./certs/confluence-client.key
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must set 'client_cert_file' when 'client_key_file'"):
        load_run_config(config_path)


def test_load_run_config_rejects_missing_confluence_tls_path_before_execution(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/missing-ca.pem
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ca_bundle"):
        load_run_config(config_path)


def test_run_command_passes_confluence_tls_config_to_real_client(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from knowledge_adapters.confluence import client as client_module

    observed_kwargs: list[dict[str, object]] = []

    def stub_real_fetch(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        observed_kwargs.append(dict(kwargs))
        return {
            "canonical_id": "12345",
            "title": "Real Page",
            "content": "<p>Hello from Confluence.</p>",
            "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
            "page_version": 7,
            "last_modified": "2026-04-20T12:34:56Z",
        }

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    (certs_dir / "internal-ca.pem").write_text("ca\n", encoding="utf-8")
    (certs_dir / "confluence-client.crt").write_text("cert\n", encoding="utf-8")
    (certs_dir / "confluence-client.key").write_text("key\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    client_mode: real
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/internal-ca.pem
    client_cert_file: ./certs/confluence-client.crt
    client_key_file: ./certs/confluence-client.key
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    assert observed_kwargs == [
        {
            "base_url": "https://example.com/wiki",
            "auth_method": "bearer-env",
            "ca_bundle": str((tmp_path / "certs" / "internal-ca.pem").resolve()),
            "client_cert_file": str((tmp_path / "certs" / "confluence-client.crt").resolve()),
            "client_key_file": str((tmp_path / "certs" / "confluence-client.key").resolve()),
        }
    ]


def test_run_command_uses_same_real_client_ca_bundle_as_direct_cli(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    observed_cafiles: list[str | None] = []
    observed_request_urls: list[str] = []
    ca_bundle = tmp_path / "internal-ca.pem"
    ca_bundle.write_text("ca\n", encoding="utf-8")

    class FakeSSLContext:
        def load_cert_chain(self, *, certfile: str, keyfile: str | None = None) -> None:
            del certfile, keyfile

    def fake_create_default_context(*, cafile: str | None = None) -> FakeSSLContext:
        observed_cafiles.append(cafile)
        return FakeSSLContext()

    def fake_urlopen(api_request: object, context: object | None = None) -> _FakeHTTPResponse:
        del context
        observed_request_urls.append(str(cast(Any, api_request).full_url))
        return _FakeHTTPResponse(
            {
                "id": "12345",
                "title": "Real Page",
                "body": {"storage": {"value": "<p>Hello from Confluence.</p>"}},
                "_links": {
                    "base": "https://example.com/wiki",
                    "webui": "/spaces/ENG/pages/12345",
                },
                "version": {
                    "number": 7,
                    "when": "2026-04-20T12:34:56Z",
                },
            }
        )

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        fake_create_default_context,
    )
    monkeypatch.setattr(
        "knowledge_adapters.confluence.client.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "token")

    direct_exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            "12345",
            "--output-dir",
            str(tmp_path / "direct-out"),
            "--client-mode",
            "real",
            "--ca-bundle",
            str(ca_bundle),
        ]
    )

    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        f"""
runs:
  - name: docs-home
    type: confluence
    client_mode: real
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./run-out
    ca_bundle: {ca_bundle}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_exit_code = main(["run", str(config_path)])

    expected_api_url = (
        "https://example.com/wiki/rest/api/content/12345?expand=body.storage,_links,version"
    )
    assert direct_exit_code == 0
    assert run_exit_code == 0
    assert observed_cafiles == [str(ca_bundle), str(ca_bundle)]
    assert observed_request_urls == [expected_api_url, expected_api_url]


def test_run_debug_flag_propagates_safe_confluence_debug_details(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module
    from knowledge_adapters.confluence.client import ConfluenceRequestError

    ca_bundle = tmp_path / "internal-ca.pem"
    ca_bundle.write_text("ca\n", encoding="utf-8")

    def stub_real_fetch(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        raise ConfluenceRequestError(
            "Confluence TLS handshake failed. Check --ca-bundle or client certificate settings.",
            request_url="https://example.com/wiki/rest/api/content/12345",
            auth_method="bearer-env",
            underlying_error="[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
        )

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "token")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        f"""
runs:
  - name: docs-home
    type: confluence
    client_mode: real
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: {ca_bundle}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="2"):
        main(["run", "--debug", str(config_path)])

    captured = capsys.readouterr()
    assert (
        "command: knowledge-adapters confluence --base-url https://example.com/wiki "
        "--target 12345 --output-dir "
    ) in captured.out
    assert "--client-mode real --ca-bundle " in captured.out
    assert "--debug" in captured.out
    assert (
        "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while executing "
    ) in captured.err
    assert "Confluence TLS handshake failed. Check --ca-bundle or client certificate settings." in (
        captured.err
    )
    assert "debug request_url: https://example.com/wiki/rest/api/content/12345" in captured.err
    assert "debug client_mode: real" in captured.err
    assert "debug auth_method: bearer-env" in captured.err
