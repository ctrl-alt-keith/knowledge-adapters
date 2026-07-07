"""Lifecycle classification helpers for the github_metadata adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from knowledge_adapters.incremental_sync import SyncChangeKey, classify_incremental_sync
from knowledge_adapters.manifest_stale import PreviousManifestEntry

GitHubMetadataSyncStatus = Literal["new", "changed", "unchanged"]


@dataclass(frozen=True)
class GitHubMetadataSyncDecision:
    """Lifecycle decision plus an operator-facing deterministic reason."""

    status: GitHubMetadataSyncStatus
    reason: str


def classify_github_metadata_sync(
    output_dir: str,
    previous_manifest_index: dict[str, PreviousManifestEntry] | None,
    *,
    manifest_entry: Mapping[str, object],
) -> GitHubMetadataSyncDecision:
    """Classify one planned GitHub metadata artifact for lifecycle visibility."""
    canonical_id = manifest_entry.get("canonical_id")
    if not isinstance(canonical_id, str) or not canonical_id:
        return GitHubMetadataSyncDecision(status="new", reason="canonical_id missing")

    output_path = manifest_entry.get("output_path")
    normalized_output_path = output_path if isinstance(output_path, str) else ""

    content_hash = manifest_entry.get("content_hash")
    normalized_content_hash = (
        content_hash if isinstance(content_hash, str) and content_hash else None
    )
    decision = classify_incremental_sync(
        output_dir,
        previous_manifest_index,
        canonical_id=canonical_id,
        output_path=normalized_output_path,
        change_keys=(
            SyncChangeKey(
                name="content_hash",
                current_value=normalized_content_hash,
                unchanged_reason="content_hash unchanged",
            ),
        ),
        no_previous_manifest_reason="no previous manifest",
        missing_metadata_reason="prior manifest entry missing content_hash",
        missing_output_path_reason="output_path missing",
        missing_current_change_key_reason="content_hash missing",
        missing_previous_change_key_reason="prior manifest entry missing content_hash",
    )
    return GitHubMetadataSyncDecision(status=decision.status, reason=decision.reason or "")
