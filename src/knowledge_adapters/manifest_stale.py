"""Shared helpers for stale-artifact reporting across manifest-backed adapters."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreviousManifestEntry:
    """Normalized prior-manifest entry used for stale-artifact comparisons."""

    canonical_id: str
    output_path: str
    page_version: str | None
    last_modified: str | None


@dataclass(frozen=True)
class StaleArtifact:
    """Previously written artifact no longer part of the current run output."""

    canonical_id: str
    output_path: str


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
    path = Path(output_dir) / "manifest.json"
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


def find_stale_artifacts(
    output_dir: str,
    previous_manifest_index: dict[str, PreviousManifestEntry] | None,
    *,
    current_output_paths: Collection[str],
) -> list[StaleArtifact]:
    """Return prior manifest artifacts no longer present in the current run output."""
    if previous_manifest_index is None:
        return []

    current_paths = frozenset(current_output_paths)
    output_dir_path = Path(output_dir)
    stale_artifacts: list[StaleArtifact] = []

    for canonical_id, prior_entry in sorted(
        previous_manifest_index.items(),
        key=lambda item: (item[1].output_path, item[0]),
    ):
        if prior_entry.output_path in current_paths:
            continue

        artifact_path = output_dir_path / prior_entry.output_path
        if not artifact_path.exists():
            continue

        stale_artifacts.append(
            StaleArtifact(
                canonical_id=canonical_id,
                output_path=prior_entry.output_path,
            )
        )

    return stale_artifacts
