from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def assert_single_page_confluence_dry_run_summary(
    output: str,
    *,
    client_mode: str,
    content_source: str,
    page_id: str,
    source_url: str,
    artifact_path: Path,
    manifest_path: Path,
    auth_method: str | None = None,
    action: str = "write",
    write_count: int = 1,
    skip_count: int = 0,
) -> None:
    assert "Confluence adapter invoked" in output
    assert f"client_mode: {client_mode}" in output
    assert f"content_source: {content_source}" in output
    assert "fetch_scope: page" in output
    assert "run_mode: dry-run" in output
    if auth_method is None:
        assert "auth_method:" not in output
    else:
        assert f"auth_method: {auth_method}" in output

    assert "Plan: Confluence run" in output
    assert f"resolved_page_id: {page_id}" in output
    assert f"source_url: {source_url}" in output
    assert f"artifact_path: {artifact_path}" in output
    assert f"manifest_path: {manifest_path}" in output
    assert f"action: would {action}" in output
    assert f"Summary: would write {write_count}, would skip {skip_count}" in output


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
) -> None:
    assert "Confluence adapter invoked" in output
    assert f"client_mode: {client_mode}" in output
    assert f"content_source: {content_source}" in output
    assert "fetch_scope: tree" in output
    assert "run_mode: dry-run" in output
    if auth_method is None:
        assert "auth_method:" not in output
    else:
        assert f"auth_method: {auth_method}" in output

    assert "Plan: Confluence run" in output
    assert f"resolved_root_page_id: {root_page_id} (root page)" in output
    assert f"max_depth: {max_depth}" in output
    assert f"manifest_path: {manifest_path}" in output
    assert f"unique_pages: {unique_pages} (root + descendants)" in output
    for action, path in planned_actions:
        assert f"would {action} {path}" in output
    assert f"Summary: would write {write_count}, would skip {skip_count}" in output
