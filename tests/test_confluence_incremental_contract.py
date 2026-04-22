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
    pages: dict[str, dict[str, object]] | None = None,
    target: str = "100",
    max_depth: int = 1,
    dry_run: bool = False,
) -> tuple[int, Path]:
    pages = pages or _synthetic_pages()

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
    generated_at: str = "2026-04-19T00:00:00Z",
    root_page_id: str | None = None,
    max_depth: int | None = None,
) -> str:
    payload: dict[str, object] = {
        "generated_at": generated_at,
        "files": files,
    }
    if root_page_id is not None:
        payload["root_page_id"] = root_page_id
    if max_depth is not None:
        payload["max_depth"] = max_depth

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
    assert (
        "  Summary:\n"
        "    mode: tree\n"
        "    pages_in_plan: 2 (root 1, descendants 1)\n"
        "    would_write: 1\n"
        "    would_skip: 1\n"
    ) in captured.out
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


def test_incremental_normal_run_handles_larger_mixed_write_and_skip_set(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    pages: dict[str, dict[str, object]] = {
        "100": {
            "canonical_id": "100",
            "title": "Root",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root content.",
            "children": ["200", "300", "400"],
        },
        "200": {
            "canonical_id": "200",
            "title": "Write Child A",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Child A content.",
            "children": [],
        },
        "300": {
            "canonical_id": "300",
            "title": "Skip Child",
            "source_url": "https://example.com/wiki/pages/300",
            "content": "Child B content.",
            "children": [],
        },
        "400": {
            "canonical_id": "400",
            "title": "Write Child B",
            "source_url": "https://example.com/wiki/pages/400",
            "content": "Child C content.",
            "children": [],
        },
    }
    output_dir = tmp_path / "out"
    _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100?old=1",
                "output_path": "pages/100.md",
                "title": "Old Root",
            },
            {
                "canonical_id": "300",
                "source_url": "https://example.com/wiki/pages/300?old=1",
                "output_path": "pages/300.md",
                "title": "Old Child",
            },
            {
                "canonical_id": "999",
                "source_url": "https://example.com/wiki/pages/999",
                "output_path": "pages/999.md",
                "title": "Unrelated",
            },
        ],
        root_page_id="old-root",
        max_depth=9,
    )
    existing_pages = [
        ("100", "existing root\n"),
        ("300", "existing child\n"),
        ("999", "existing unrelated\n"),
    ]
    for page_id, contents in existing_pages:
        path = _page_path(output_dir, page_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        pages=pages,
        max_depth=1,
    )

    assert exit_code == 0
    assert _page_path(output_dir, "100").read_text(encoding="utf-8") == "existing root\n"
    assert _page_path(output_dir, "300").read_text(encoding="utf-8") == "existing child\n"
    assert _page_path(output_dir, "200").exists()
    assert _page_path(output_dir, "400").exists()

    payload = _load_manifest(output_dir)
    assert payload["root_page_id"] == "100"
    assert payload["max_depth"] == 1
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "200",
        "300",
        "400",
    ]

    captured = capsys.readouterr()
    assert f"Skipped: {_page_path(output_dir, '100')}" in captured.out
    assert f"Skipped: {_page_path(output_dir, '300')}" in captured.out
    assert f"Wrote: {_page_path(output_dir, '200')}" in captured.out
    assert f"Wrote: {_page_path(output_dir, '400')}" in captured.out
    assert "Summary: wrote 2, skipped 2" in captured.out


def test_incremental_dry_run_ignores_non_identity_manifest_fields_for_skip(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "100",
                "source_url": "https://example.com/wiki/pages/100?stale=1",
                "output_path": "pages/100.md",
                "title": "Stale Root Title",
            }
        ],
        generated_at="1999-12-31T23:59:59Z",
        root_page_id="different-root",
        max_depth=99,
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
    assert (
        "  Summary:\n"
        "    mode: tree\n"
        "    pages_in_plan: 2 (root 1, descendants 1)\n"
        "    would_write: 1\n"
        "    would_skip: 1\n"
    ) in captured.out


def test_incremental_run_fails_fast_for_duplicate_output_paths_in_prior_manifest(
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
                "output_path": "pages/shared.md",
            },
            {
                "canonical_id": "200",
                "source_url": "https://example.com/wiki/pages/200",
                "output_path": "pages/shared.md",
            },
            {
                "canonical_id": "300",
                "source_url": "https://example.com/wiki/pages/300",
                "output_path": "pages/300.md",
            },
        ],
        root_page_id="100",
    )

    with pytest.raises((RuntimeError, ValueError, SystemExit)):
        _run_recursive_cli(
            tmp_path,
            monkeypatch,
            dry_run=True,
        )

    assert not _page_path(output_dir, "100").exists()
    assert not _page_path(output_dir, "200").exists()


def test_incremental_output_directory_reuse_handles_overlapping_and_new_pages(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "200",
                "source_url": "https://example.com/wiki/pages/200?old=1",
                "output_path": "pages/200.md",
            },
            {
                "canonical_id": "777",
                "source_url": "https://example.com/wiki/pages/777",
                "output_path": "pages/777.md",
            },
        ],
        root_page_id="100",
        max_depth=3,
    )
    overlapping_page = _page_path(output_dir, "200")
    unrelated_page = _page_path(output_dir, "777")
    for path, contents in [
        (overlapping_page, "artifact from another target\n"),
        (unrelated_page, "unrelated artifact\n"),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        target="900",
        dry_run=False,
    )

    assert exit_code == 0
    assert overlapping_page.read_text(encoding="utf-8") == "artifact from another target\n"
    assert _page_path(output_dir, "900").exists()
    assert _page_path(output_dir, "950").exists()
    assert unrelated_page.read_text(encoding="utf-8") == "unrelated artifact\n"

    payload = _load_manifest(output_dir)
    assert payload["root_page_id"] == "900"
    assert payload["max_depth"] == 1
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "900",
        "200",
        "950",
    ]

    captured = capsys.readouterr()
    assert "Summary: wrote 2, skipped 1" in captured.out


def test_incremental_dry_run_summary_reports_mixed_write_and_skip_counts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    pages: dict[str, dict[str, object]] = {
        "100": {
            "canonical_id": "100",
            "title": "Root",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root content.",
            "children": ["200", "300", "400"],
        },
        "200": {
            "canonical_id": "200",
            "title": "Skip Child",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Skip child content.",
            "children": [],
        },
        "300": {
            "canonical_id": "300",
            "title": "Write Child A",
            "source_url": "https://example.com/wiki/pages/300",
            "content": "Write child A content.",
            "children": [],
        },
        "400": {
            "canonical_id": "400",
            "title": "Write Child B",
            "source_url": "https://example.com/wiki/pages/400",
            "content": "Write child B content.",
            "children": [],
        },
    }
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
                "canonical_id": "200",
                "source_url": "https://example.com/wiki/pages/200",
                "output_path": "pages/200.md",
            },
        ],
        root_page_id="100",
    )
    for page_id in ["100", "200"]:
        path = _page_path(output_dir, page_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"existing {page_id}\n", encoding="utf-8")

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        pages=pages,
        dry_run=True,
    )

    assert exit_code == 0
    assert not _page_path(output_dir, "300").exists()
    assert not _page_path(output_dir, "400").exists()

    captured = capsys.readouterr()
    assert (
        "  Summary:\n"
        "    mode: tree\n"
        "    pages_in_plan: 4 (root 1, descendants 3)\n"
        "    would_write: 2\n"
        "    would_skip: 2\n"
    ) in captured.out
    assert "pages_in_tree: 4" in captured.out
