"""File writing utilities for the Confluence adapter."""

from __future__ import annotations

from pathlib import Path


def markdown_path(output_dir: str, page_id: str) -> Path:
    """Return the deterministic markdown path for a page."""
    return Path(output_dir) / "pages" / f"{page_id}.md"


def write_markdown(
    output_dir: str,
    page_id: str,
    markdown: str,
    *,
    dry_run: bool = False,
) -> Path:
    """Write normalized markdown to a deterministic local path."""
    output_path = markdown_path(output_dir, page_id)
    pages_dir = output_path.parent

    if dry_run:
        return output_path

    pages_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path
