"""Normalization logic for the Confluence adapter."""

from __future__ import annotations

from collections.abc import Mapping


def normalize_to_markdown(page: Mapping[str, object]) -> str:
    """Normalize a fetched page payload into markdown."""
    title = str(page.get("title", "untitled"))
    canonical_id = str(page.get("canonical_id", ""))
    parent_id = str(page.get("parent_id", ""))
    source_url = str(page.get("source_url", ""))
    fetched_at = str(page.get("fetched_at", ""))
    updated_at = str(page.get("updated_at", ""))
    source = str(page.get("source", "confluence"))
    adapter = str(page.get("adapter", "confluence"))
    content = str(page.get("content", "")).rstrip("\n")

    return f"""# {title}

## Metadata
- source: {source}
- canonical_id: {canonical_id}
- parent_id:{f" {parent_id}" if parent_id else ""}
- source_url: {source_url}
- fetched_at:{f" {fetched_at}" if fetched_at else ""}
- updated_at:{f" {updated_at}" if updated_at else ""}
- adapter: {adapter}

## Content

{content}
"""
