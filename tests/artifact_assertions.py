from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def assert_markdown_document(
    markdown: str,
    *,
    title: str,
    metadata: Mapping[str, str],
    content: str,
) -> None:
    actual_title, actual_metadata, actual_content = _parse_markdown_document(markdown)

    assert actual_title == title
    assert actual_metadata == dict(metadata)
    assert actual_content == content.rstrip("\n")


def manifest_file(
    *,
    canonical_id: str,
    source_url: str,
    output_path: str,
    title: str | None = None,
) -> dict[str, str]:
    entry = {
        "canonical_id": canonical_id,
        "source_url": source_url,
        "output_path": output_path,
    }
    if title is not None:
        entry["title"] = title
    return entry


def assert_manifest_entry(
    entry: Mapping[str, object],
    *,
    canonical_id: str,
    source_url: str,
    output_path: str,
    title: str | None = None,
) -> None:
    assert dict(entry) == manifest_file(
        canonical_id=canonical_id,
        source_url=source_url,
        output_path=output_path,
        title=title,
    )


def assert_manifest_entries(
    manifest: Path | Mapping[str, object],
    *,
    files: Sequence[Mapping[str, str]],
) -> None:
    payload = _load_manifest(manifest) if isinstance(manifest, Path) else dict(manifest)

    assert isinstance(payload.get("generated_at"), str)

    actual_files = payload.get("files")
    assert isinstance(actual_files, list)
    assert len(actual_files) == len(files)

    for actual_entry, expected_entry in zip(actual_files, files, strict=True):
        assert isinstance(actual_entry, dict)
        assert dict(actual_entry) == dict(expected_entry)


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _parse_markdown_document(markdown: str) -> tuple[str, dict[str, str], str]:
    title_block, metadata_marker, remainder = markdown.partition("\n## Metadata\n")
    assert metadata_marker

    title_lines = title_block.splitlines()
    assert title_lines
    assert title_lines[0].startswith("# ")
    assert all(not line.strip() for line in title_lines[1:])

    metadata_block, content_marker, content_block = remainder.partition("\n## Content\n")
    assert content_marker

    metadata: dict[str, str] = {}
    for line in metadata_block.splitlines():
        if not line:
            continue

        assert line.startswith("- ")
        key, separator, value = line[2:].partition(":")
        assert separator == ":"
        assert key not in metadata
        metadata[key] = value.lstrip()

    if content_block.startswith("\n"):
        content_block = content_block[1:]

    return title_lines[0][2:], metadata, content_block.rstrip("\n")
