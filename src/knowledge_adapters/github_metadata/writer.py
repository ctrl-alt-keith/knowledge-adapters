"""File writing utilities for the github_metadata adapter."""

from __future__ import annotations

from pathlib import Path


def markdown_path(output_dir: str, number: int) -> Path:
    """Return the deterministic markdown path for one issue."""
    return Path(output_dir) / "issues" / f"{number}.md"


def write_markdown(
    output_dir: str,
    number: int,
    markdown: str,
    *,
    dry_run: bool = False,
) -> Path:
    """Write normalized issue markdown to a deterministic local path."""
    output_path = markdown_path(output_dir, number)

    if dry_run:
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path

