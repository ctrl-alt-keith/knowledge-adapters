"""Opt-in traversal cache for Confluence listing discovery."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CACHE_SCHEMA_VERSION = 1
_ENTRY_FILENAME = "listing.json"


@dataclass
class ConfluenceTreeCacheStats:
    """Run-scoped traversal cache counters."""

    hits: int = 0
    misses: int = 0


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normal_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def prepare_tree_cache_dir(path_value: str) -> Path:
    """Validate and create the configured traversal cache root."""
    cache_dir = Path(path_value).expanduser().resolve()
    if cache_dir.exists() and not cache_dir.is_dir():
        raise ValueError(
            f"Confluence traversal cache path is not a directory: {cache_dir}. "
            "Verify --tree-cache-dir and use a directory path."
        )

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            f"Could not create Confluence traversal cache directory {cache_dir}: {exc}."
        ) from exc

    return cache_dir


class ConfluenceTreeCache:
    """Best-effort cache for Confluence traversal listing results."""

    def __init__(self, root_dir: Path, *, base_url: str) -> None:
        self._root_dir = root_dir
        self._base_url = _normal_base_url(base_url)
        self.stats = ConfluenceTreeCacheStats()

    def get_child_page_ids(
        self,
        parent_page_id: str,
        fetch_listing: Callable[[], list[str]],
    ) -> list[str]:
        """Return cached child page IDs, or fetch and best-effort cache them."""
        return self._get_listing(
            kind="child",
            key_name="parent_page_id",
            key_value=parent_page_id,
            fetch_listing=fetch_listing,
        )

    def get_space_page_ids(
        self,
        space_key: str,
        fetch_listing: Callable[[], list[str]],
    ) -> list[str]:
        """Return cached space page IDs, or fetch and best-effort cache them."""
        return self._get_listing(
            kind="space",
            key_name="space_key",
            key_value=space_key,
            fetch_listing=fetch_listing,
        )

    def _get_listing(
        self,
        *,
        kind: str,
        key_name: str,
        key_value: str,
        fetch_listing: Callable[[], list[str]],
    ) -> list[str]:
        try:
            page_ids = self._read_listing(kind=kind, key_name=key_name, key_value=key_value)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.stats.misses += 1
        else:
            self.stats.hits += 1
            return page_ids

        page_ids = fetch_listing()
        self._store_listing(
            kind=kind,
            key_name=key_name,
            key_value=key_value,
            page_ids=page_ids,
        )
        return page_ids

    def _entry_path(self, *, kind: str, key_value: str) -> Path:
        return (
            self._root_dir
            / "confluence"
            / _hash_value(self._base_url)
            / "traversal"
            / kind
            / _hash_value(key_value)
            / _ENTRY_FILENAME
        )

    def _read_listing(self, *, kind: str, key_name: str, key_value: str) -> list[str]:
        entry = json.loads(
            self._entry_path(kind=kind, key_value=key_value).read_text(encoding="utf-8")
        )
        if not isinstance(entry, dict):
            raise ValueError("invalid cache entry")
        return self._validate_entry(
            _as_str_object_dict(entry),
            kind=kind,
            key_name=key_name,
            key_value=key_value,
        )

    def _store_listing(
        self,
        *,
        kind: str,
        key_name: str,
        key_value: str,
        page_ids: list[str],
    ) -> None:
        entry: dict[str, object] = {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "base_url": self._base_url,
            "kind": kind,
            key_name: key_value,
            "page_ids": list(page_ids),
        }

        try:
            self._write_entry(kind=kind, key_value=key_value, entry=entry)
        except (OSError, TypeError, ValueError):
            return

    def _write_entry(self, *, kind: str, key_value: str, entry: Mapping[str, object]) -> None:
        entry_path = self._entry_path(kind=kind, key_value=key_value)
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = entry_path.with_suffix(".tmp")
        serialized_entry = f"{json.dumps(entry, indent=2, sort_keys=True)}\n"
        temporary_path.write_text(serialized_entry, encoding="utf-8")
        os.replace(temporary_path, entry_path)

    def _validate_entry(
        self,
        entry: Mapping[str, object],
        *,
        kind: str,
        key_name: str,
        key_value: str,
    ) -> list[str]:
        if entry.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError("cache schema mismatch")
        if entry.get("base_url") != self._base_url:
            raise ValueError("base_url mismatch")
        if entry.get("kind") != kind:
            raise ValueError("listing kind mismatch")
        if entry.get(key_name) != key_value:
            raise ValueError("listing key mismatch")

        page_ids = entry.get("page_ids")
        if not isinstance(page_ids, list):
            raise ValueError("invalid cached listing")
        result: list[str] = []
        for page_id in page_ids:
            if not isinstance(page_id, str) or not page_id:
                raise ValueError("invalid cached page ID")
            result.append(page_id)
        return result


def _as_str_object_dict(value: dict[Any, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("invalid cache entry")
        result[key] = item
    return result
