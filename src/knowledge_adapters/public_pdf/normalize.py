"""Normalization logic for the public PDF/report adapter."""

from __future__ import annotations

from collections.abc import Mapping


def normalize_to_markdown(page: Mapping[str, object]) -> str:
    """Normalize a fetched public PDF/report into reviewable candidate markdown."""
    title = str(page.get("title", "untitled"))
    canonical_id = str(page.get("canonical_id", ""))
    source_url = str(page.get("source_url", ""))
    fetched_at = str(page.get("fetched_at", ""))
    source = str(page.get("source", "public_pdf"))
    adapter = str(page.get("adapter", "public_pdf"))
    page_count = str(page.get("page_count", ""))
    extraction_notes = str(page.get("extraction_notes", "Unreviewed candidate material."))
    content = str(page.get("content", "")).rstrip("\n")

    return f"""# {title}

## Metadata
- source: {source}
- canonical_id: {canonical_id}
- parent_id:
- source_url: {source_url}
- fetched_at: {fetched_at}
- updated_at:
- adapter: {adapter}
- candidate_status: unreviewed
- page_count: {page_count}
- extraction_notes: {extraction_notes}

## Content

> This is unreviewed candidate material generated from an external public PDF/report.

{content}
"""
