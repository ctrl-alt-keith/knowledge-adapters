from __future__ import annotations

from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.confluence.client import map_real_page_payload
from knowledge_adapters.confluence.fetch_cache import (
    ConfluenceFetchCache,
    clear_fetch_cache_entries,
    prepare_fetch_cache_dir,
)
from knowledge_adapters.manifest import build_manifest_entry, write_manifest


def _confluence_argv(
    output_dir: Path,
    *,
    fetch_cache_dir: Path | None = None,
    force_refresh: bool = False,
    clear_cache: bool = False,
) -> list[str]:
    argv = [
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        str(output_dir),
        "--client-mode",
        "real",
    ]
    if fetch_cache_dir is not None:
        argv.extend(["--fetch-cache-dir", str(fetch_cache_dir)])
    if force_refresh:
        argv.append("--force-refresh")
    if clear_cache:
        argv.append("--clear-cache")
    return argv


def _raw_payload(
    *,
    page_version: int | None = 7,
    last_modified: str | None = "2026-04-20T12:34:56Z",
    content: str = "<p>Hello from Confluence.</p>",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "12345",
        "title": "Real Page",
        "body": {"storage": {"value": content}},
        "_links": {
            "base": "https://example.com/wiki",
            "webui": "/spaces/ENG/pages/12345",
        },
    }
    if page_version is not None or last_modified is not None:
        version: dict[str, object] = {}
        if page_version is not None:
            version["number"] = page_version
        if last_modified is not None:
            version["when"] = last_modified
        payload["version"] = version
    return payload


def _write_prior_manifest(output_dir: Path, *, page_version: int = 6) -> None:
    page_path = output_dir / "pages" / "12345.md"
    page_path.parent.mkdir(parents=True)
    page_path.write_text("# Previous\n", encoding="utf-8")
    write_manifest(
        str(output_dir),
        [
            build_manifest_entry(
                canonical_id="12345",
                source_url="https://example.com/wiki/spaces/ENG/pages/12345",
                output_path=page_path,
                output_dir=str(output_dir),
                title="Real Page",
                page_version=page_version,
                last_modified="2026-04-19T12:34:56Z",
            )
        ],
    )


def _store_cached_payload(cache_dir: Path, raw_payload: dict[str, object]) -> None:
    cache = ConfluenceFetchCache(
        prepare_fetch_cache_dir(str(cache_dir)),
        base_url="https://example.com/wiki",
    )
    cache.store_page(map_real_page_payload(raw_payload, "12345"), raw_payload)


def _cache_entry_path(cache_dir: Path) -> Path:
    return next(cache_dir.rglob("page.json"))


def test_fetch_cache_force_refresh_bypasses_cached_payload(tmp_path: Path) -> None:
    cache = ConfluenceFetchCache(
        prepare_fetch_cache_dir(str(tmp_path / "cache")),
        base_url="https://example.com/wiki",
        force_refresh=True,
    )
    cached_payload = _raw_payload(content="<p>Cached.</p>")
    cache.record_metadata(map_real_page_payload(cached_payload, "12345"))
    cache.store_page(map_real_page_payload(cached_payload, "12345"), cached_payload)

    assert cache.load_page("12345") is None
    assert cache.stats.hits == 0
    assert cache.stats.misses == 0


def test_clear_fetch_cache_entries_removes_only_fetch_subtree(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _store_cached_payload(cache_dir, _raw_payload())
    entry_path = _cache_entry_path(cache_dir)
    traversal_sibling = entry_path.parents[2] / "traversal" / "child" / "abc" / "listing.json"
    traversal_sibling.parent.mkdir(parents=True)
    traversal_sibling.write_text("{}", encoding="utf-8")

    assert clear_fetch_cache_entries(
        prepare_fetch_cache_dir(str(cache_dir)),
        base_url="https://example.com/wiki",
    )

    assert not entry_path.exists()
    assert traversal_sibling.exists()


def test_confluence_fetch_cache_disabled_keeps_output_unchanged(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    requests: list[str] = []

    def request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        requests.append(api_url)
        return _raw_payload()

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)

    exit_code = main(_confluence_argv(tmp_path / "out"))

    assert exit_code == 0
    assert len(requests) == 1
    captured = capsys.readouterr()
    assert "cache_hits:" not in captured.out
    assert "cache_misses:" not in captured.out


def test_confluence_fetch_cache_hit_uses_cached_raw_payload(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    _write_prior_manifest(output_dir, page_version=6)
    _store_cached_payload(cache_dir, _raw_payload())
    requests: list[str] = []

    def request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        requests.append(api_url)
        if "expand=version" in api_url:
            return _raw_payload()
        raise AssertionError("full page fetch should be satisfied by cache")

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)

    exit_code = main(_confluence_argv(output_dir, fetch_cache_dir=cache_dir))

    assert exit_code == 0
    assert len(requests) == 1
    captured = capsys.readouterr()
    assert "cache_hits: 1" in captured.out
    assert "cache_misses: 0" in captured.out
    assert "Hello from Confluence." in (output_dir / "pages" / "12345.md").read_text(
        encoding="utf-8"
    )


def test_confluence_force_refresh_bypasses_fetch_cache_hit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    _write_prior_manifest(output_dir, page_version=6)
    _store_cached_payload(cache_dir, _raw_payload(content="<p>Cached content.</p>"))
    requests: list[str] = []

    def request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        requests.append(api_url)
        return _raw_payload(content="<p>Fresh content.</p>")

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)

    exit_code = main(
        _confluence_argv(output_dir, fetch_cache_dir=cache_dir, force_refresh=True)
    )

    assert exit_code == 0
    assert len(requests) == 2
    captured = capsys.readouterr()
    assert "force_refresh: enabled; configured cache reads will be bypassed" in captured.out
    assert "cache_hits: 0" in captured.out
    assert "cache_misses: 0" in captured.out
    output = (output_dir / "pages" / "12345.md").read_text(encoding="utf-8")
    assert "Fresh content." in output
    assert "Cached content." not in output


def test_confluence_clear_cache_removes_stale_fetch_entry_before_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    _write_prior_manifest(output_dir, page_version=6)
    _store_cached_payload(cache_dir, _raw_payload(content="<p>Stale cached content.</p>"))
    requests: list[str] = []

    def request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        requests.append(api_url)
        return _raw_payload(content="<p>Fresh content.</p>")

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)

    exit_code = main(_confluence_argv(output_dir, fetch_cache_dir=cache_dir, clear_cache=True))

    assert exit_code == 0
    assert len(requests) == 2
    captured = capsys.readouterr()
    assert "fetch_cache: cleared configured entries" in captured.out
    assert "cache_hits: 0" in captured.out
    assert "cache_misses: 1" in captured.out
    output = (output_dir / "pages" / "12345.md").read_text(encoding="utf-8")
    assert "Fresh content." in output
    assert "Stale cached content." not in output


def test_confluence_fetch_cache_miss_on_metadata_mismatch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    _write_prior_manifest(output_dir, page_version=6)
    _store_cached_payload(cache_dir, _raw_payload(page_version=6))
    requests: list[str] = []

    def request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        requests.append(api_url)
        return _raw_payload(page_version=7)

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)

    exit_code = main(_confluence_argv(output_dir, fetch_cache_dir=cache_dir))

    assert exit_code == 0
    assert len(requests) == 2
    captured = capsys.readouterr()
    assert "cache_hits: 0" in captured.out
    assert "cache_misses: 1" in captured.out


def test_confluence_fetch_cache_miss_when_metadata_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    _write_prior_manifest(output_dir, page_version=6)
    _store_cached_payload(cache_dir, _raw_payload())
    requests: list[str] = []

    def request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        requests.append(api_url)
        if "expand=version" in api_url:
            return _raw_payload(page_version=None, last_modified=None)
        return _raw_payload()

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)

    exit_code = main(_confluence_argv(output_dir, fetch_cache_dir=cache_dir))

    assert exit_code == 0
    assert len(requests) == 2
    captured = capsys.readouterr()
    assert "cache_hits: 0" in captured.out
    assert "cache_misses: 1" in captured.out


def test_confluence_fetch_cache_corrupted_entry_falls_back_to_fetch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    _write_prior_manifest(output_dir, page_version=6)
    _store_cached_payload(cache_dir, _raw_payload())
    _cache_entry_path(cache_dir).write_text("{not json\n", encoding="utf-8")
    requests: list[str] = []

    def request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        requests.append(api_url)
        return _raw_payload()

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)

    exit_code = main(_confluence_argv(output_dir, fetch_cache_dir=cache_dir))

    assert exit_code == 0
    assert len(requests) == 2
    captured = capsys.readouterr()
    assert "cache_hits: 0" in captured.out
    assert "cache_misses: 1" in captured.out


def test_confluence_fetch_cache_write_failure_does_not_break_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    def request_json(_api_url: str, **_kwargs: object) -> dict[str, object]:
        return _raw_payload()

    def write_entry(
        _self: ConfluenceFetchCache,
        _canonical_id: str,
        _entry: object,
    ) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr("knowledge_adapters.confluence.client._request_json", request_json)
    monkeypatch.setattr(ConfluenceFetchCache, "_write_entry", write_entry)

    exit_code = main(_confluence_argv(tmp_path / "out", fetch_cache_dir=tmp_path / "cache"))

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "cache_hits: 0" in captured.out
    assert "cache_misses: 1" in captured.out


def test_confluence_fetch_cache_preserves_deterministic_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_output_dir = tmp_path / "from-cache"
    fetch_output_dir = tmp_path / "from-fetch"
    _write_prior_manifest(cache_output_dir, page_version=6)
    _write_prior_manifest(fetch_output_dir, page_version=6)
    _store_cached_payload(cache_dir, _raw_payload())

    def cached_request_json(api_url: str, **_kwargs: object) -> dict[str, object]:
        if "expand=version" in api_url:
            return _raw_payload()
        raise AssertionError("full page fetch should be satisfied by cache")

    monkeypatch.setattr(
        "knowledge_adapters.confluence.client._request_json",
        cached_request_json,
    )
    assert main(_confluence_argv(cache_output_dir, fetch_cache_dir=cache_dir)) == 0

    def fetched_request_json(_api_url: str, **_kwargs: object) -> dict[str, object]:
        return _raw_payload()

    monkeypatch.setattr(
        "knowledge_adapters.confluence.client._request_json",
        fetched_request_json,
    )
    assert main(_confluence_argv(fetch_output_dir)) == 0

    assert (cache_output_dir / "pages" / "12345.md").read_text(encoding="utf-8") == (
        fetch_output_dir / "pages" / "12345.md"
    ).read_text(encoding="utf-8")


def test_confluence_fetch_cache_rejects_file_path(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    cache_path = tmp_path / "cache-file"
    cache_path.write_text("not a dir", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(_confluence_argv(tmp_path / "out", fetch_cache_dir=cache_path))

    captured = capsys.readouterr()
    assert "Confluence fetch cache path is not a directory" in captured.err
