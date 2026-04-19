"""Manifest handling for the Confluence adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def manifest_path(output_dir: str) -> Path:
    """Return the manifest path for an output directory."""
    return Path(output_dir) / "manifest.json"


def build_manifest_entry(
    *,
    canonical_id: str,
    source_url: str,
    output_path: Path,
    output_dir: str,
    title: str | None = None,
) -> dict[str, str]:
    """Build a minimal manifest entry for a generated file."""
    entry = {
        "canonical_id": canonical_id,
        "source_url": source_url,
        "output_path": output_path.relative_to(Path(output_dir)).as_posix(),
    }

    if title:
        entry["title"] = title

    return entry


def write_manifest(output_dir: str, files: list[dict[str, str]]) -> Path:
    """Write a per-run manifest describing generated files."""
    return write_manifest_with_context(output_dir, files)


def write_manifest_with_context(
    output_dir: str,
    files: list[dict[str, str]],
    *,
    root_page_id: str | None = None,
    max_depth: int | None = None,
) -> Path:
    """Write a per-run manifest describing generated files."""
    path = manifest_path(output_dir)
    payload: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if root_page_id is not None:
        payload["root_page_id"] = root_page_id
    if max_depth is not None:
        payload["max_depth"] = max_depth
    payload["files"] = files

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")
    return path
