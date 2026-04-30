from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.artifact_assertions import parse_markdown_document

DEFAULT_MARKDOWN_METADATA_FIELDS = (
    "source",
    "canonical_id",
    "parent_id",
    "source_url",
    "fetched_at",
    "updated_at",
    "adapter",
)

DEFAULT_MANIFEST_ENTRY_FIELDS = (
    "canonical_id",
    "source_url",
    "output_path",
)


def assert_normalized_markdown_contract(
    markdown: str,
    *,
    source: str,
    adapter: str,
    canonical_id: str,
    source_url: str,
    title: str | None = None,
    content: str | None = None,
    required_metadata_fields: Sequence[str] = DEFAULT_MARKDOWN_METADATA_FIELDS,
) -> None:
    actual_title, metadata, actual_content = parse_markdown_document(markdown)

    if title is None:
        assert actual_title.strip()
    else:
        assert actual_title == title

    for field in required_metadata_fields:
        assert field in metadata

    assert metadata["source"] == source
    assert metadata["adapter"] == adapter
    assert metadata["canonical_id"] == canonical_id
    assert metadata["source_url"] == source_url
    assert metadata["source"].strip()
    assert metadata["adapter"].strip()
    assert metadata["canonical_id"].strip()
    assert metadata["source_url"].strip()

    if content is None:
        assert actual_content.strip()
    else:
        assert actual_content == content.rstrip("\n")


def assert_manifest_success_contract(
    manifest: Path | Mapping[str, object],
    *,
    expected_files: Sequence[Mapping[str, object]] | None = None,
    required_entry_fields: Sequence[str] = DEFAULT_MANIFEST_ENTRY_FIELDS,
) -> None:
    payload = _load_manifest(manifest) if isinstance(manifest, Path) else dict(manifest)

    generated_at = payload.get("generated_at")
    assert isinstance(generated_at, str)
    assert generated_at.strip()

    files = payload.get("files")
    assert isinstance(files, list)
    if expected_files is not None:
        assert len(files) == len(expected_files)

    for index, entry in enumerate(files):
        assert isinstance(entry, dict)
        _assert_manifest_entry_contract(entry, required_entry_fields=required_entry_fields)

        if expected_files is None:
            continue

        for key, value in expected_files[index].items():
            assert entry.get(key) == value


def assert_no_partial_adapter_artifacts(
    output_dir: Path,
    *,
    artifact_patterns: Sequence[str] = ("**/*.md",),
    manifest_name: str = "manifest.json",
) -> None:
    assert not (output_dir / manifest_name).exists()
    if not output_dir.exists():
        return

    partial_artifacts: list[Path] = []
    for pattern in artifact_patterns:
        partial_artifacts.extend(path for path in output_dir.glob(pattern) if path.is_file())

    assert partial_artifacts == []


def _assert_manifest_entry_contract(
    entry: Mapping[str, object],
    *,
    required_entry_fields: Sequence[str],
) -> None:
    for field in required_entry_fields:
        assert field in entry
        value = entry[field]
        assert isinstance(value, str)
        assert value.strip()

    output_path = entry["output_path"]
    assert isinstance(output_path, str)
    assert not Path(output_path).is_absolute()

    title = entry.get("title")
    if title is not None:
        assert isinstance(title, str)
        assert title.strip()


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload
