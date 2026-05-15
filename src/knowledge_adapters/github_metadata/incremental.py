"""Lifecycle classification helpers for the github_metadata adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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

    if previous_manifest_index is None:
        return GitHubMetadataSyncDecision(status="new", reason="no previous manifest")

    prior_entry = previous_manifest_index.get(canonical_id)
    if prior_entry is None:
        return GitHubMetadataSyncDecision(
            status="new",
            reason="prior manifest entry missing entirely",
        )

    output_path = manifest_entry.get("output_path")
    if not isinstance(output_path, str) or not output_path:
        return GitHubMetadataSyncDecision(status="changed", reason="output_path missing")

    if prior_entry.output_path != output_path:
        return GitHubMetadataSyncDecision(status="changed", reason="output_path changed")

    if not (Path(output_dir) / prior_entry.output_path).exists():
        return GitHubMetadataSyncDecision(
            status="changed",
            reason="prior artifact missing, so safe rewrite",
        )

    content_hash = manifest_entry.get("content_hash")
    if not isinstance(content_hash, str) or not content_hash:
        return GitHubMetadataSyncDecision(status="changed", reason="content_hash missing")

    if prior_entry.content_hash is None:
        return GitHubMetadataSyncDecision(
            status="changed",
            reason="prior manifest entry missing content_hash",
        )

    if prior_entry.content_hash != content_hash:
        return GitHubMetadataSyncDecision(status="changed", reason="content_hash changed")

    return GitHubMetadataSyncDecision(status="unchanged", reason="content_hash unchanged")
