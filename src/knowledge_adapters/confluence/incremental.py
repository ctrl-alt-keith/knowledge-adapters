"""Incremental sync helpers for the Confluence adapter."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_adapters.confluence.manifest import manifest_path


def _load_previous_manifest_indexes(
    output_dir: str,
) -> tuple[dict[str, str], dict[str, str]] | None:
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

    entries_by_id: dict[str, str] = {}
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

        entries_by_id[canonical_id] = output_path
        entries_by_output_path[output_path] = canonical_id

    return entries_by_id, entries_by_output_path


def load_previous_manifest_index(output_dir: str) -> dict[str, str] | None:
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


def is_already_written(
    output_dir: str,
    previous_manifest_index: dict[str, str] | None,
    *,
    canonical_id: str,
    output_path: Path,
) -> bool:
    """Return whether the candidate page is already written for v1 sync rules."""
    if previous_manifest_index is None:
        return False

    expected_output_path = output_path.relative_to(Path(output_dir)).as_posix()
    prior_output_path = previous_manifest_index.get(canonical_id)
    if prior_output_path != expected_output_path:
        return False

    return (Path(output_dir) / prior_output_path).exists()
