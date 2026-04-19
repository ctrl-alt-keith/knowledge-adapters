from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.confluence.models import ResolvedTarget


def _synthetic_pages() -> dict[str, dict[str, object]]:
    return {
        "100": {
            "canonical_id": "100",
            "title": "Root A",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root A content.",
            "children": ["200"],
        },
        "200": {
            "canonical_id": "200",
            "title": "Shared Child",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Shared child content.",
            "children": [],
        },
        "900": {
            "canonical_id": "900",
            "title": "Root B",
            "source_url": "https://example.com/wiki/pages/900",
            "content": "Root B content.",
            "children": ["200", "950"],
        },
        "950": {
            "canonical_id": "950",
            "title": "Exclusive Child",
            "source_url": "https://example.com/wiki/pages/950",
            "content": "Exclusive child content.",
            "children": [],
        },
    }


def _run_recursive_cli(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    target: str = "100",
    max_depth: int = 1,
    dry_run: bool = False,
) -> tuple[int, Path]:
    pages = _synthetic_pages()

    def stub_fetch_page(target: ResolvedTarget) -> dict[str, object]:
        return dict(pages[str(target.page_id)])

    monkeypatch.setattr("knowledge_adapters.confluence.client.fetch_page", stub_fetch_page)

    output_dir = tmp_path / "out"
    argv = [
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        target,
        "--output-dir",
        str(output_dir),
        "--tree",
        "--max-depth",
        str(max_depth),
    ]
    if dry_run:
        argv.append("--dry-run")

    return main(argv), output_dir


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / "manifest.json"


def _page_path(output_dir: Path, page_id: str) -> Path:
    return output_dir / "pages" / f"{page_id}.md"


def _write_previous_manifest(
    output_dir: Path,
    files: list[dict[str, str]],
    *,
    root_page_id: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "generated_at": "2026-04-19T00:00:00Z",
        "files": files,
    }
    if root_page_id is not None:
        payload["root_page_id"] = root_page_id

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(payload, indent=2) + "\n"
    _manifest_path(output_dir).write_text(manifest_text, encoding="utf-8")
    return manifest_text


def _load_manifest(output_dir: Path) -> dict[str, object]:
    payload = json.loads(_manifest_path(output_dir).read_text(encoding="utf-8"))
    return cast(dict[str, object], payload)


def _manifest_files(payload: dict[str, object]) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], payload["files"])


def test_incremental_dry_run_without_manifest_marks_all_pages_as_write(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    exit_code, output_dir = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        dry_run=True,
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert f"would write {_page_path(output_dir, '100')}" in captured.out
    assert f"would write {_page_path(output_dir, '200')}" in captured.out
    assert f"would skip {_page_path(output_dir, '100')}" not in captured.out
    assert f"would skip {_page_path(output_dir, '200')}" not in captured.out
    assert not _page_path(output_dir, "100").exists()
    assert not _page_path(output_dir, "200").exists()
    assert not _manifest_path(output_dir).exists()


@pytest.mark.parametrize(
    ("manifest_entry", "materialize_file", "expected_phrase"),
    [
        (
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100",
                "output_path": "pages/100.md",
            },
            True,
            "would skip",
        ),
        (
            {
                "canonical_id": "999",
                "source_url": "https://example.com/wiki/pages/999",
                "output_path": "pages/100.md",
            },
            True,
            "would write",
        ),
        (
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100",
                "output_path": "pages/custom-name.md",
            },
            True,
            "would write",
        ),
        (
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100",
                "output_path": "pages/100.md",
            },
            False,
            "would write",
        ),
    ],
)
def test_incremental_dry_run_uses_manifest_identity_and_file_existence_for_skip(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    manifest_entry: dict[str, str],
    materialize_file: bool,
    expected_phrase: str,
) -> None:
    output_dir = tmp_path / "out"
    original_manifest = _write_previous_manifest(
        output_dir,
        [manifest_entry],
        root_page_id="100",
    )

    if materialize_file:
        prior_path = output_dir / manifest_entry["output_path"]
        prior_path.parent.mkdir(parents=True, exist_ok=True)
        prior_path.write_text("existing artifact\n", encoding="utf-8")

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        dry_run=True,
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert f"{expected_phrase} {_page_path(output_dir, '100')}" in captured.out
    if materialize_file and manifest_entry["output_path"] == "pages/100.md":
        assert _page_path(output_dir, "100").read_text(encoding="utf-8") == "existing artifact\n"
    else:
        assert not _page_path(output_dir, "100").exists()
    assert _manifest_path(output_dir).read_text(encoding="utf-8") == original_manifest


def test_incremental_dry_run_reports_both_would_write_and_would_skip_without_writing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    original_manifest = _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100",
                "output_path": "pages/100.md",
            }
        ],
        root_page_id="100",
    )
    existing_page = _page_path(output_dir, "100")
    existing_page.parent.mkdir(parents=True, exist_ok=True)
    existing_page.write_text("already written\n", encoding="utf-8")

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        dry_run=True,
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert f"would skip {existing_page}" in captured.out
    assert f"would write {_page_path(output_dir, '200')}" in captured.out
    assert existing_page.read_text(encoding="utf-8") == "already written\n"
    assert not _page_path(output_dir, "200").exists()
    assert _manifest_path(output_dir).read_text(encoding="utf-8") == original_manifest


def test_incremental_normal_run_manifest_includes_written_and_skipped_pages(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100",
                "output_path": "pages/100.md",
            }
        ],
        root_page_id="100",
    )
    existing_page = _page_path(output_dir, "100")
    existing_page.parent.mkdir(parents=True, exist_ok=True)
    existing_page.write_text("already written\n", encoding="utf-8")

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        dry_run=False,
    )

    assert exit_code == 0
    assert existing_page.read_text(encoding="utf-8") == "already written\n"
    assert _page_path(output_dir, "200").exists()

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == ["100", "200"]


def test_incremental_output_directory_reuse_skips_overlapping_pages_without_target_validation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "200",
                "source_url": "https://example.com/wiki/pages/200",
                "output_path": "pages/200.md",
            }
        ],
        root_page_id="100",
    )
    overlapping_page = _page_path(output_dir, "200")
    overlapping_page.parent.mkdir(parents=True, exist_ok=True)
    overlapping_page.write_text("artifact from another target\n", encoding="utf-8")

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        target="900",
        dry_run=False,
    )

    assert exit_code == 0
    assert overlapping_page.read_text(encoding="utf-8") == "artifact from another target\n"

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == ["900", "200", "950"]


def test_incremental_run_fails_fast_for_malformed_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(output_dir)
    manifest_path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises((RuntimeError, ValueError, SystemExit)):
        _run_recursive_cli(
            tmp_path,
            monkeypatch,
            dry_run=False,
        )

    assert not _page_path(output_dir, "100").exists()
    assert manifest_path.read_text(encoding="utf-8") == "{not-json}\n"


def test_incremental_run_fails_fast_for_duplicate_manifest_entries(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100",
                "output_path": "pages/100.md",
            },
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100?duplicate=1",
                "output_path": "pages/100-duplicate.md",
            },
        ],
        root_page_id="100",
    )

    with pytest.raises((RuntimeError, ValueError, SystemExit)):
        _run_recursive_cli(
            tmp_path,
            monkeypatch,
            dry_run=False,
        )

    assert not _page_path(output_dir, "100").exists()
