"""Recursive traversal helpers for the Confluence adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from knowledge_adapters.confluence.models import ResolvedTarget

PagePayload = Mapping[str, object]
FetchPage = Callable[[ResolvedTarget], dict[str, object]]
ListChildPageIds = Callable[[ResolvedTarget], list[str]]


def _canonical_id(page: PagePayload, fallback_page_id: str) -> str:
    """Return the canonical page ID for a fetched page."""
    return str(page.get("canonical_id") or fallback_page_id)


def _child_page_ids(page: PagePayload) -> list[str]:
    """Extract child page IDs from a fetched page payload."""
    children = page.get("children", [])
    if not isinstance(children, list):
        return []
    return [str(child) for child in children]


def _target_for_page(page: PagePayload) -> ResolvedTarget:
    """Build a resolved target from an already-fetched page payload."""
    canonical_id = _canonical_id(page, "")
    if not canonical_id:
        raise ValueError("Response error: invalid canonical_id.")

    return ResolvedTarget(
        raw_value=canonical_id,
        page_id=canonical_id,
        page_url=None,
    )


def walk_pages(
    root_target: ResolvedTarget,
    *,
    max_depth: int,
    fetch_page: FetchPage,
    list_child_page_ids: ListChildPageIds | None = None,
) -> tuple[str, list[dict[str, object]]]:
    """Fetch pages breadth-first up to the requested depth."""
    root_page = fetch_page(root_target)
    root_page_id = _canonical_id(root_page, root_target.page_id or "")

    ordered_pages = [root_page]
    fetched_pages = {root_page_id: root_page}
    current_level = [root_page]

    for _depth in range(max_depth):
        child_ids: set[str] = set()
        for page in current_level:
            page_child_ids = (
                list_child_page_ids(_target_for_page(page))
                if list_child_page_ids is not None
                else _child_page_ids(page)
            )
            child_ids.update(
                child_id
                for child_id in page_child_ids
                if child_id not in fetched_pages
            )

        next_level: list[dict[str, object]] = []
        for child_id in sorted(child_ids):
            child_target = ResolvedTarget(
                raw_value=child_id,
                page_id=child_id,
                page_url=None,
            )
            page = fetch_page(child_target)
            canonical_id = _canonical_id(page, child_id)
            if canonical_id in fetched_pages:
                continue
            fetched_pages[canonical_id] = page
            next_level.append(page)

        current_level = sorted(
            next_level,
            key=lambda page: _canonical_id(page, ""),
        )
        ordered_pages.extend(current_level)

    return root_page_id, ordered_pages
