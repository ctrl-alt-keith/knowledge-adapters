from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def assert_contains_normalized(output: str, expected: str) -> None:
    assert normalize_whitespace(expected) in normalize_whitespace(output)


def assert_stale_artifacts(
    output: str,
    *,
    count: int,
    artifact_paths: Iterable[Path] = (),
) -> None:
    assert f"stale_artifacts: {count}" in output
    if count == 0:
        assert "Stale artifacts:" not in output
        return

    assert "Stale artifacts:" in output
    for path in artifact_paths:
        assert_contains_normalized(output, str(path))


def assert_dry_run_summary(
    output: str,
    *,
    would_write: int,
    would_skip: int,
    new_pages: int | None = None,
    changed_pages: int | None = None,
    unchanged_pages: int | None = None,
) -> None:
    normalized = normalize_whitespace(output)
    legacy_summary = f"Summary: would write {would_write}, would skip {would_skip}"
    if legacy_summary in normalized:
        return

    assert "Summary:" in output
    assert f"would_write: {would_write}" in output
    assert f"would_skip: {would_skip}" in output
    if new_pages is not None:
        assert f"new_pages: {new_pages}" in output
    if changed_pages is not None:
        assert f"changed_pages: {changed_pages}" in output
    if unchanged_pages is not None:
        assert f"unchanged_pages: {unchanged_pages}" in output


def assert_write_summary(
    output: str,
    *,
    wrote: int,
    skipped: int,
    new_pages: int | None = None,
    changed_pages: int | None = None,
    unchanged_pages: int | None = None,
    stale_artifacts: int | None = None,
) -> None:
    normalized = normalize_whitespace(output)
    if f"Summary: wrote {wrote}, skipped {skipped}" in normalized:
        pass
    elif skipped == 0 and (
        f"Summary: wrote {wrote} file" in normalized
        or f"Summary: wrote {wrote} files" in normalized
    ):
        pass
    else:
        raise AssertionError(
            f"expected write summary for wrote={wrote}, skipped={skipped} in output:\n{output}"
        )

    if new_pages is not None:
        assert f"new_pages: {new_pages}" in output
    if changed_pages is not None:
        assert f"changed_pages: {changed_pages}" in output
    if unchanged_pages is not None:
        assert f"unchanged_pages: {unchanged_pages}" in output
    if stale_artifacts is not None:
        assert f"stale_artifacts: {stale_artifacts}" in output
    if any(value is not None for value in (new_pages, changed_pages, unchanged_pages)):
        assert f"pages_written: {wrote}" in output
        assert f"pages_skipped: {skipped}" in output


def assert_tree_plan_page_count(output: str, *, count: int) -> None:
    assert (
        f"unique_pages: {count}" in output
        or f"pages_in_tree: {count}" in output
        or f"pages_in_plan: {count}" in output
    )
