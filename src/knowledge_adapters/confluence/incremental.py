"""Incremental sync helpers for the Confluence adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from knowledge_adapters.incremental_sync import SyncChangeKey, classify_incremental_sync
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
    expected_output_path = output_path.relative_to(Path(output_dir)).as_posix()
    current_page_version = _normalize_metadata_value(page.get("page_version"))
    current_last_modified = _normalize_metadata_value(page.get("last_modified"))
    decision = classify_incremental_sync(
        output_dir,
        previous_manifest_index,
        canonical_id=canonical_id,
        output_path=expected_output_path,
        change_keys=(
            SyncChangeKey(name="page_version", current_value=current_page_version),
            SyncChangeKey(name="last_modified", current_value=current_last_modified),
        ),
        no_previous_manifest_reason="new page",
        missing_metadata_reason="prior manifest entry missing metadata, so safe rewrite",
    )
    return PageSyncDecision(status=decision.status, rewrite_reason=decision.reason)
