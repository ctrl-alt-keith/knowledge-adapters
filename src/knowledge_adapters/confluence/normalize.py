"""Normalization logic for the Confluence adapter."""

from __future__ import annotations

from collections.abc import Mapping


def normalize_to_markdown(page: Mapping[str, object]) -> str:
    """Normalize a fetched page payload into markdown."""
    title = str(page.get("title", "untitled"))
    canonical_id = str(page.get("canonical_id", ""))
    source_url = str(page.get("source_url", ""))
    content = str(page.get("content", ""))

    return f"""# {title}

## Metadata
- source: confluence
- canonical_id: {canonical_id}
- parent_id:
- source_url: {source_url}
- fetched_at:
- updated_at:
- adapter: confluence

## Content

{content}
"""
