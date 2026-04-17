"""HTTP/client layer for the Confluence adapter."""

from __future__ import annotations

from knowledge_adapters.confluence.models import ResolvedTarget


def fetch_page(target: ResolvedTarget) -> dict[str, object]:
    """Fetch a Confluence page.

    This is a stub for the initial scaffold.
    """
    canonical_id = target.page_id or "unknown"

    return {
        "title": f"stub-page-{canonical_id}",
        "canonical_id": canonical_id,
        "source_url": target.page_url or "",
        "content": f"Stub content for page {canonical_id}.",
    }