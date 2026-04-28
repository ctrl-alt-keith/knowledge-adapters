"""Opt-in raw payload cache for Confluence full-page fetches."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from knowledge_adapters.confluence.client import map_real_page_payload

CACHE_SCHEMA_VERSION = 1
_ENTRY_FILENAME = "page.json"


@dataclass
class ConfluenceFetchCacheStats:
    """Run-scoped cache counters."""

    hits: int = 0
    misses: int = 0


@dataclass(frozen=True)
class _PageMetadata:
    page_version: int
    last_modified: str | None


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normal_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def prepare_fetch_cache_dir(path_value: str) -> Path:
    """Validate and create the run-scoped cache root."""
    cache_dir = Path(path_value).expanduser().resolve()
    if cache_dir.exists() and not cache_dir.is_dir():
        raise ValueError(
            f"Confluence fetch cache path is not a directory: {cache_dir}. "
            "Verify --fetch-cache-dir and use a directory path."
        )

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            f"Could not create Confluence fetch cache directory {cache_dir}: {exc}."
        ) from exc

    return cache_dir


def clear_fetch_cache_entries(root_dir: Path, *, base_url: str) -> bool:
    """Delete known fetch-cache entries under the configured cache root."""
    cache_subtree = _fetch_cache_subtree(root_dir, base_url=base_url)
    if not cache_subtree.exists():
        return False
    if cache_subtree.is_symlink() or not cache_subtree.is_dir():
        cache_subtree.unlink()
        return True
    shutil.rmtree(cache_subtree)
    return True


class ConfluenceFetchCache:
    """Best-effort cache for raw Confluence full-page payloads."""

    def __init__(self, root_dir: Path, *, base_url: str, force_refresh: bool = False) -> None:
        self._root_dir = root_dir
        self._base_url = _normal_base_url(base_url)
        self._force_refresh = force_refresh
        self._metadata_by_id: dict[str, _PageMetadata] = {}
        self.stats = ConfluenceFetchCacheStats()

    def record_metadata(self, page: Mapping[str, object]) -> None:
        """Remember metadata fetched by the existing summary request path."""
        canonical_id = page.get("canonical_id")
        page_version = page.get("page_version")
        if not isinstance(canonical_id, str) or not canonical_id or not _is_int(page_version):
            return

        last_modified_value = page.get("last_modified")
        last_modified = (
            last_modified_value
            if isinstance(last_modified_value, str) and last_modified_value
            else None
        )
        self._metadata_by_id[canonical_id] = _PageMetadata(
            page_version=page_version,
            last_modified=last_modified,
        )

    def load_page(self, canonical_id: str) -> dict[str, object] | None:
        """Return a mapped cached page when metadata and payload are valid."""
        if self._force_refresh:
            return None

        metadata = self._metadata_by_id.get(canonical_id)
        if metadata is None:
            self.stats.misses += 1
            return None

        try:
            entry = self._read_entry(canonical_id)
            mapped_page = self._validate_entry(
                entry,
                canonical_id=canonical_id,
                metadata=metadata,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.stats.misses += 1
            return None

        self.stats.hits += 1
        return mapped_page

    def store_page(self, page: Mapping[str, object], raw_payload: Mapping[str, object]) -> None:
        """Best-effort write of one raw fetched page payload."""
        canonical_id = page.get("canonical_id")
        page_version = page.get("page_version")
        if not isinstance(canonical_id, str) or not canonical_id or not _is_int(page_version):
            return

        last_modified_value = page.get("last_modified")
        last_modified = (
            last_modified_value
            if isinstance(last_modified_value, str) and last_modified_value
            else None
        )
        entry: dict[str, object] = {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "base_url": self._base_url,
            "canonical_id": canonical_id,
            "page_version": page_version,
            "last_modified": last_modified,
            "payload": dict(raw_payload),
        }

        try:
            self._write_entry(canonical_id, entry)
        except (OSError, TypeError, ValueError):
            return

    def _entry_path(self, canonical_id: str) -> Path:
        return (
            _fetch_cache_subtree(self._root_dir, base_url=self._base_url)
            / _hash_value(canonical_id)
            / _ENTRY_FILENAME
        )

    def _read_entry(self, canonical_id: str) -> Mapping[str, object]:
        entry = json.loads(self._entry_path(canonical_id).read_text(encoding="utf-8"))
        if not isinstance(entry, dict):
            raise ValueError("invalid cache entry")
        return entry

    def _write_entry(self, canonical_id: str, entry: Mapping[str, object]) -> None:
        entry_path = self._entry_path(canonical_id)
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = entry_path.with_suffix(".tmp")
        serialized_entry = f"{json.dumps(entry, indent=2, sort_keys=True)}\n"
        temporary_path.write_text(serialized_entry, encoding="utf-8")
        os.replace(temporary_path, entry_path)

    def _validate_entry(
        self,
        entry: Mapping[str, object],
        *,
        canonical_id: str,
        metadata: _PageMetadata,
    ) -> dict[str, object]:
        if entry.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError("cache schema mismatch")
        if entry.get("base_url") != self._base_url:
            raise ValueError("base_url mismatch")
        if entry.get("canonical_id") != canonical_id:
            raise ValueError("canonical_id mismatch")
        if entry.get("page_version") != metadata.page_version:
            raise ValueError("page_version mismatch")

        entry_last_modified = entry.get("last_modified")
        if (
            isinstance(entry_last_modified, str)
            and entry_last_modified
            and metadata.last_modified is not None
            and entry_last_modified != metadata.last_modified
        ):
            raise ValueError("last_modified mismatch")

        raw_payload = entry.get("payload")
        if not isinstance(raw_payload, dict):
            raise ValueError("invalid cached payload")

        mapped_page = map_real_page_payload(
            _as_str_object_dict(raw_payload),
            canonical_id,
        )
        if mapped_page.get("page_version") != metadata.page_version:
            raise ValueError("payload page_version mismatch")

        payload_last_modified = mapped_page.get("last_modified")
        if (
            isinstance(payload_last_modified, str)
            and payload_last_modified
            and metadata.last_modified is not None
            and payload_last_modified != metadata.last_modified
        ):
            raise ValueError("payload last_modified mismatch")

        return mapped_page


def _as_str_object_dict(value: dict[Any, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("invalid cached payload")
        result[key] = item
    return result


def _fetch_cache_subtree(root_dir: Path, *, base_url: str) -> Path:
    return root_dir / "confluence" / _hash_value(_normal_base_url(base_url)) / "pages"
