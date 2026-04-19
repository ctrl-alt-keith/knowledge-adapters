"""Target resolution for the Confluence adapter."""

from __future__ import annotations

import re

from knowledge_adapters.confluence.models import ResolvedTarget

_PAGE_ID_RE = re.compile(r"^\d+$")
_PAGE_ID_IN_URL_RE = re.compile(r"/pages/(?:viewpage\.action\?pageId=)?(\d+)")


def resolve_target(target: str) -> ResolvedTarget:
    """Resolve a user-provided target into a canonical form.

    Supports:
    - numeric page IDs
    - URLs containing a page ID
    """
    cleaned = target.strip()

    if _PAGE_ID_RE.fullmatch(cleaned):
        return ResolvedTarget(
            raw_value=cleaned,
            page_id=cleaned,
            page_url=None,
        )

    url_match = _PAGE_ID_IN_URL_RE.search(cleaned)
    if url_match:
        return ResolvedTarget(
            raw_value=cleaned,
            page_id=url_match.group(1),
            page_url=cleaned,
        )

    return ResolvedTarget(
        raw_value=cleaned,
        page_id=None,
        page_url=cleaned if "://" in cleaned else None,
    )
