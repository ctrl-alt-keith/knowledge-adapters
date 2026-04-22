from __future__ import annotations


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def assert_contains_normalized(output: str, expected: str) -> None:
    assert normalize_whitespace(expected) in normalize_whitespace(output)


def assert_dry_run_summary(
    output: str,
    *,
    would_write: int,
    would_skip: int,
) -> None:
    normalized = normalize_whitespace(output)
    legacy_summary = f"Summary: would write {would_write}, would skip {would_skip}"
    if legacy_summary in normalized:
        return

    assert "Summary:" in output
    assert f"would_write: {would_write}" in output
    assert f"would_skip: {would_skip}" in output


def assert_write_summary(output: str, *, wrote: int, skipped: int) -> None:
    normalized = normalize_whitespace(output)
    if f"Summary: wrote {wrote}, skipped {skipped}" in normalized:
        return

    if skipped == 0 and (
        f"Summary: wrote {wrote} file" in normalized
        or f"Summary: wrote {wrote} files" in normalized
    ):
        return

    raise AssertionError(
        f"expected write summary for wrote={wrote}, skipped={skipped} in output:\n{output}"
    )


def assert_tree_plan_page_count(output: str, *, count: int) -> None:
    assert (
        f"unique_pages: {count}" in output
        or f"pages_in_tree: {count}" in output
        or f"pages_in_plan: {count}" in output
    )
