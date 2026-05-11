"""File writing utilities for the public webpage adapter."""

from __future__ import annotations

from pathlib import Path

from knowledge_adapters.public_sources import output_name_for_url


def markdown_path(output_dir: str, url: str) -> Path:
    """Return the deterministic markdown path for one public webpage."""
    return Path(output_dir) / "pages" / f"{output_name_for_url(url)}.md"


def write_markdown(
    output_dir: str,
    url: str,
    markdown: str,
    *,
    dry_run: bool = False,
) -> Path:
    """Write normalized markdown to a deterministic local path."""
    output_path = markdown_path(output_dir, url)
    if dry_run:
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path
