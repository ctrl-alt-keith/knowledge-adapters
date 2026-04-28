from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from knowledge_adapters.confluence.tree_cache import (
    ConfluenceTreeCache,
    clear_tree_cache_entries,
    prepare_tree_cache_dir,
)


def test_tree_cache_miss_fetches_and_stores_listing(tmp_path: Path) -> None:
    cache = ConfluenceTreeCache(tmp_path / "cache", base_url="https://example.com/wiki/")
    fetch_calls = 0

    def fetch_listing() -> list[str]:
        nonlocal fetch_calls
        fetch_calls += 1
        return ["200", "300"]

    assert cache.get_child_page_ids("100", fetch_listing) == ["200", "300"]

    assert fetch_calls == 1
    assert cache.stats.hits == 0
    assert cache.stats.misses == 1
    assert list((tmp_path / "cache").rglob("listing.json"))


def test_tree_cache_hit_returns_cached_child_listing(tmp_path: Path) -> None:
    cache = ConfluenceTreeCache(tmp_path / "cache", base_url="https://example.com/wiki")

    assert cache.get_child_page_ids("100", lambda: ["200"]) == ["200"]
    assert cache.get_child_page_ids("100", lambda: pytest.fail("unexpected fetch")) == ["200"]

    assert cache.stats.hits == 1
    assert cache.stats.misses == 1


def test_tree_cache_force_refresh_bypasses_cached_listing(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    priming_cache = ConfluenceTreeCache(cache_dir, base_url="https://example.com/wiki")
    assert priming_cache.get_child_page_ids("100", lambda: ["200"]) == ["200"]

    cache = ConfluenceTreeCache(
        cache_dir,
        base_url="https://example.com/wiki",
        force_refresh=True,
    )

    assert cache.get_child_page_ids("100", lambda: ["300"]) == ["300"]
    assert cache.stats.hits == 0
    assert cache.stats.misses == 0


def test_clear_tree_cache_entries_removes_only_traversal_subtree(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ConfluenceTreeCache(cache_dir, base_url="https://example.com/wiki")
    assert cache.get_child_page_ids("100", lambda: ["200"]) == ["200"]
    listing_path = next(cache_dir.rglob("listing.json"))
    fetch_sibling = listing_path.parents[3] / "pages" / "abc" / "page.json"
    fetch_sibling.parent.mkdir(parents=True)
    fetch_sibling.write_text("{}", encoding="utf-8")

    assert clear_tree_cache_entries(
        prepare_tree_cache_dir(str(cache_dir)),
        base_url="https://example.com/wiki",
    )

    assert not listing_path.exists()
    assert fetch_sibling.exists()


def test_tree_cache_corrupt_entry_falls_back_to_fetch(tmp_path: Path) -> None:
    cache = ConfluenceTreeCache(tmp_path / "cache", base_url="https://example.com/wiki")
    assert cache.get_child_page_ids("100", lambda: ["200"]) == ["200"]
    listing_path = next((tmp_path / "cache").rglob("listing.json"))
    listing_path.write_text("{not valid json", encoding="utf-8")

    assert cache.get_child_page_ids("100", lambda: ["300"]) == ["300"]

    assert cache.stats.hits == 0
    assert cache.stats.misses == 2


def test_tree_cache_write_failure_does_not_fail_lookup(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache = ConfluenceTreeCache(tmp_path / "cache", base_url="https://example.com/wiki")

    def raise_write_error(
        self: ConfluenceTreeCache,
        *,
        kind: str,
        key_value: str,
        entry: object,
    ) -> None:
        del self, kind, key_value, entry
        raise OSError("synthetic write failure")

    monkeypatch.setattr(ConfluenceTreeCache, "_write_entry", raise_write_error)

    assert cache.get_child_page_ids("100", lambda: ["200"]) == ["200"]
    assert cache.stats.hits == 0
    assert cache.stats.misses == 1


def test_prepare_tree_cache_dir_rejects_file_path(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache-file"
    cache_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="Verify --tree-cache-dir"):
        prepare_tree_cache_dir(str(cache_path))
