from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from tests.artifact_assertions import (
    assert_manifest_entries,
    assert_markdown_document,
    manifest_file,
)
from tests.integration.helpers import ConfluenceStubServer


def _confluence_argv(
    base_url: str,
    output_dir: Path,
    *,
    fetch_cache_dir: Path | None = None,
) -> list[str]:
    argv = [
        "confluence",
        "--client-mode",
        "real",
        "--base-url",
        base_url,
        "--target",
        "12345",
        "--output-dir",
        str(output_dir),
    ]
    if fetch_cache_dir is not None:
        argv.extend(["--fetch-cache-dir", str(fetch_cache_dir)])
    return argv


def _load_manifest(output_dir: Path) -> dict[str, object]:
    payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _set_manifest_page_version(output_dir: Path, *, page_version: int) -> None:
    manifest = _load_manifest(output_dir)
    files = manifest.get("files")
    assert isinstance(files, list)
    assert len(files) == 1
    entry = files[0]
    assert isinstance(entry, dict)
    entry["page_version"] = page_version
    (output_dir / "manifest.json").write_text(
        f"{json.dumps(manifest, indent=2)}\n",
        encoding="utf-8",
    )


@pytest.mark.integration
def test_confluence_cli_writes_stub_page_through_real_client_path(
    tmp_path: Path,
    confluence_stub_server: ConfluenceStubServer,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "stub-token")
    output_dir = tmp_path / "artifacts"

    exit_code = main(_confluence_argv(confluence_stub_server.base_url, output_dir))

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Summary: wrote 1, skipped 0" in captured.out

    page_path = output_dir / "pages" / "12345.md"
    assert_markdown_document(
        page_path.read_text(encoding="utf-8"),
        title="Test Page",
        metadata={
            "source": "confluence",
            "canonical_id": "12345",
            "parent_id": "",
            "source_url": f"{confluence_stub_server.base_url}/pages/viewpage.action?pageId=12345",
            "fetched_at": "",
            "updated_at": "",
            "adapter": "confluence",
        },
        content="Hello world",
    )
    assert_manifest_entries(
        output_dir / "manifest.json",
        files=[
            manifest_file(
                canonical_id="12345",
                source_url=f"{confluence_stub_server.base_url}/pages/viewpage.action?pageId=12345",
                output_path="pages/12345.md",
                title="Test Page",
                page_version=1,
                last_modified="2026-04-20T12:34:56Z",
            )
        ],
    )


@pytest.mark.integration
def test_confluence_cli_reuses_fetch_cache_on_second_fetch(
    tmp_path: Path,
    confluence_stub_server: ConfluenceStubServer,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "stub-token")
    output_dir = tmp_path / "artifacts"
    cache_dir = tmp_path / "cache"

    first_exit_code = main(
        _confluence_argv(
            confluence_stub_server.base_url,
            output_dir,
            fetch_cache_dir=cache_dir,
        )
    )

    assert first_exit_code == 0
    first_run = capsys.readouterr()
    assert "cache_hits: 0" in first_run.out
    assert "cache_misses: 1" in first_run.out
    assert len(list(cache_dir.rglob("page.json"))) == 1

    # Downgrade the local manifest to simulate stale local metadata while the
    # remote summary still matches the cached full payload. That forces the
    # real summary-plus-full-fetch path on the second run and verifies cache reuse.
    _set_manifest_page_version(output_dir, page_version=0)

    second_exit_code = main(
        _confluence_argv(
            confluence_stub_server.base_url,
            output_dir,
            fetch_cache_dir=cache_dir,
        )
    )

    assert second_exit_code == 0
    second_run = capsys.readouterr()
    assert "Summary: wrote 1, skipped 0" in second_run.out
    assert "cache_hits: 1" in second_run.out
    assert "cache_misses: 0" in second_run.out
