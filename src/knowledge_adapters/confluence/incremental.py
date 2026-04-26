"""Incremental sync helpers for the Confluence adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from knowledge_adapters.manifest_stale import PreviousManifestEntry

PageSyncStatus = Literal["new", "changed", "unchanged"]


@dataclass(frozen=True)
class PageSyncDecision:
    """Incremental sync decision plus an operator-facing rewrite reason."""

    status: PageSyncStatus
    rewrite_reason: str | None = None


def _normalize_metadata_value(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def classify_page_sync(
    output_dir: str,
    previous_manifest_index: dict[str, PreviousManifestEntry] | None,
    *,
    page: Mapping[str, object],
    output_path: Path,
) -> PageSyncDecision:
    """Classify a page as new, changed, or unchanged for incremental sync."""
    canonical_id = str(page.get("canonical_id") or "")
    if previous_manifest_index is None:
        return PageSyncDecision(status="new", rewrite_reason="new page")

    prior_entry = previous_manifest_index.get(canonical_id)
    if prior_entry is None:
        return PageSyncDecision(
            status="new",
            rewrite_reason="prior manifest entry missing entirely",
        )

    expected_output_path = output_path.relative_to(Path(output_dir)).as_posix()
    if prior_entry.output_path != expected_output_path:
        return PageSyncDecision(status="changed", rewrite_reason="output_path changed")

    if not (Path(output_dir) / prior_entry.output_path).exists():
        return PageSyncDecision(
            status="changed",
            rewrite_reason="prior artifact missing, so safe rewrite",
        )

    current_page_version = _normalize_metadata_value(page.get("page_version"))
    if current_page_version is not None and prior_entry.page_version is not None:
        if current_page_version == prior_entry.page_version:
            return PageSyncDecision(status="unchanged")
        return PageSyncDecision(status="changed", rewrite_reason="page_version changed")

    current_last_modified = _normalize_metadata_value(page.get("last_modified"))
    if current_last_modified is not None and prior_entry.last_modified is not None:
        if current_last_modified == prior_entry.last_modified:
            return PageSyncDecision(status="unchanged")
        return PageSyncDecision(status="changed", rewrite_reason="last_modified changed")

    return PageSyncDecision(
        status="changed",
        rewrite_reason="prior manifest entry missing metadata, so safe rewrite",
    )
