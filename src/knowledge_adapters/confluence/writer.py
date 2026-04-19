"""File writing utilities for the Confluence adapter."""

from __future__ import annotations

from pathlib import Path


def write_markdown(output_dir: str, page_id: str, markdown: str) -> Path:
    """Write normalized markdown to a deterministic local path."""
    pages_dir = Path(output_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    output_path = pages_dir / f"{page_id}.md"
    output_path.write_text(markdown, encoding="utf-8")
    return output_path
