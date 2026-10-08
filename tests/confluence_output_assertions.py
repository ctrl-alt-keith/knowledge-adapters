from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from tests.cli_output_assertions import (
    assert_contains_normalized,
    assert_dry_run_summary,
    assert_stale_artifacts,
    assert_tree_plan_page_count,
)


def assert_tree_confluence_dry_run_summary(
    output: str,
    *,
    root_page_id: str,
    manifest_path: Path,
    max_depth: int,
    unique_pages: int,
    write_count: int,
    skip_count: int,
    client_mode: str = "stub",
    content_source: str = "scaffolded page content",
    auth_method: str | None = None,
    planned_actions: Iterable[tuple[str, Path]] = (),
    stale_count: int = 0,
    stale_artifact_paths: Iterable[Path] = (),
) -> None:
    assert "Confluence adapter invoked" in output
    assert f"client_mode: {client_mode}" in output
    assert f"content_source: {content_source}" in output
    assert "mode: tree" in output
    assert "run_mode: dry-run" in output
    if auth_method is None:
        assert "auth_method:" not in output
    else:
        assert f"auth_method: {auth_method}" in output

    assert "Plan: Confluence run" in output
    assert_contains_normalized(output, f"resolved_root_page_id: {root_page_id} (root page)")
    assert f"max_depth: {max_depth}" in output
    assert_contains_normalized(output, f"Manifest: {manifest_path}")
    assert_tree_plan_page_count(output, count=unique_pages)
    assert_dry_run_summary(output, would_write=write_count, would_skip=skip_count)
    assert_stale_artifacts(
        output,
        count=stale_count,
        artifact_paths=stale_artifact_paths,
    )
    for action, path in planned_actions:
        assert_contains_normalized(output, f"would {action} {path}")
    assert "Dry run complete. No files written." in output
