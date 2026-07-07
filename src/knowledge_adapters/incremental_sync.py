"""Shared incremental sync classification primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from knowledge_adapters.manifest_stale import PreviousManifestEntry

SyncStatus = Literal["new", "changed", "unchanged"]


@dataclass(frozen=True)
class SyncChangeKey:
    """One adapter-specific field used to detect source changes."""

    name: str
    current_value: str | None
    changed_reason: str | None = None
    unchanged_reason: str | None = None


@dataclass(frozen=True)
class SyncDecision:
    """Generic incremental sync decision plus an optional operator-facing reason."""

    status: SyncStatus
    reason: str | None = None


def classify_incremental_sync(
    output_dir: str,
    previous_manifest_index: Mapping[str, PreviousManifestEntry] | None,
    *,
    canonical_id: str,
    output_path: str,
    change_keys: Sequence[SyncChangeKey],
    no_previous_manifest_reason: str,
    missing_metadata_reason: str,
    missing_prior_entry_reason: str = "prior manifest entry missing entirely",
    missing_output_path_reason: str | None = None,
    artifact_missing_reason: str = "prior artifact missing, so safe rewrite",
    output_path_changed_reason: str = "output_path changed",
    missing_current_change_key_reason: str | None = None,
    missing_previous_change_key_reason: str | None = None,
) -> SyncDecision:
    """Classify whether a manifest-backed artifact should be written or skipped."""
    if previous_manifest_index is None:
        return SyncDecision(status="new", reason=no_previous_manifest_reason)

    prior_entry = previous_manifest_index.get(canonical_id)
    if prior_entry is None:
        return SyncDecision(status="new", reason=missing_prior_entry_reason)

    if not output_path:
        reason = missing_output_path_reason or output_path_changed_reason
        return SyncDecision(status="changed", reason=reason)

    if prior_entry.output_path != output_path:
        return SyncDecision(status="changed", reason=output_path_changed_reason)

    if not (Path(output_dir) / prior_entry.output_path).exists():
        return SyncDecision(status="changed", reason=artifact_missing_reason)

    all_current_values_missing = True
    any_current_value_without_prior = False
    for change_key in change_keys:
        if change_key.current_value is None:
            continue

        all_current_values_missing = False
        prior_value = getattr(prior_entry, change_key.name, None)
        if prior_value is None:
            any_current_value_without_prior = True
            continue

        if change_key.current_value == prior_value:
            return SyncDecision(status="unchanged", reason=change_key.unchanged_reason)

        return SyncDecision(
            status="changed",
            reason=change_key.changed_reason or f"{change_key.name} changed",
        )

    if all_current_values_missing and missing_current_change_key_reason is not None:
        return SyncDecision(status="changed", reason=missing_current_change_key_reason)

    if any_current_value_without_prior and missing_previous_change_key_reason is not None:
        return SyncDecision(status="changed", reason=missing_previous_change_key_reason)

    return SyncDecision(status="changed", reason=missing_metadata_reason)
