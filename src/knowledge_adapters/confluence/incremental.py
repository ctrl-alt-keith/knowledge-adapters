"""Incremental sync helpers for the Confluence adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from knowledge_adapters.confluence.manifest import manifest_path


@dataclass(frozen=True)
class PreviousManifestEntry:
    """Normalized prior-manifest entry used for incremental comparisons."""

    canonical_id: str
    output_path: str
    page_version: str | None
    last_modified: str | None


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


def _load_previous_manifest_indexes(
    output_dir: str,
) -> tuple[dict[str, PreviousManifestEntry], dict[str, str]] | None:
    """Load and validate the previous manifest for incremental comparisons."""
    path = manifest_path(output_dir)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read prior manifest {path}. Fix or remove the manifest and try again."
        ) from exc

    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError(
            f"Prior manifest {path} is invalid: expected a files list. "
            "Fix or remove the manifest and try again."
        )

    entries_by_id: dict[str, PreviousManifestEntry] = {}
    entries_by_output_path: dict[str, str] = {}

    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"Prior manifest {path} is invalid: each files entry must be an object. "
                "Fix or remove the manifest and try again."
            )

        canonical_id = entry.get("canonical_id")
        output_path = entry.get("output_path")
        if not isinstance(canonical_id, str) or not isinstance(output_path, str):
            raise RuntimeError(
                f"Prior manifest {path} is invalid: files entries must include string "
                "canonical_id and output_path values. Fix or remove the manifest and try again."
            )

        if canonical_id in entries_by_id:
            raise RuntimeError(
                f"Prior manifest {path} is invalid: duplicate canonical_id {canonical_id!r}. "
                "Fix or remove the manifest and try again."
            )
        if output_path in entries_by_output_path:
            raise RuntimeError(
                f"Prior manifest {path} is invalid: duplicate output_path {output_path!r}. "
                "Fix or remove the manifest and try again."
            )

        entries_by_id[canonical_id] = PreviousManifestEntry(
            canonical_id=canonical_id,
            output_path=output_path,
            page_version=_normalize_metadata_value(entry.get("page_version")),
            last_modified=_normalize_metadata_value(entry.get("last_modified")),
        )
        entries_by_output_path[output_path] = canonical_id

    return entries_by_id, entries_by_output_path


def load_previous_manifest_index(output_dir: str) -> dict[str, PreviousManifestEntry] | None:
    """Load and validate the previous manifest keyed by canonical_id."""
    indexes = _load_previous_manifest_indexes(output_dir)
    if indexes is None:
        return None

    return indexes[0]


def load_previous_manifest_output_index(output_dir: str) -> dict[str, str] | None:
    """Load and validate the previous manifest keyed by output_path."""
    indexes = _load_previous_manifest_indexes(output_dir)
    if indexes is None:
        return None

    return indexes[1]


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
