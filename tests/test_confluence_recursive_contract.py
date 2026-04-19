import json
from pathlib import Path
from typing import cast

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.confluence.models import ResolvedTarget

pytestmark = pytest.mark.xfail(
    reason="Recursive Confluence traversal is not implemented yet.",
    strict=True,
)


def _synthetic_pages() -> dict[str, dict[str, object]]:
    return {
        "100": {
            "canonical_id": "100",
            "title": "Root Page",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root content.",
            "children": ["300", "200"],
        },
        "200": {
            "canonical_id": "200",
            "title": "Shared Child",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Shared child content.",
            "children": ["205"],
        },
        "300": {
            "canonical_id": "300",
            "title": "Sibling Child",
            "source_url": "https://example.com/wiki/pages/300",
            "content": "Sibling child content.",
            "children": ["210", "200"],
        },
        "205": {
            "canonical_id": "205",
            "title": "Grandchild A",
            "source_url": "https://example.com/wiki/pages/205",
            "content": "Grandchild A content.",
            "children": [],
        },
        "210": {
            "canonical_id": "210",
            "title": "Grandchild B",
            "source_url": "https://example.com/wiki/pages/210",
            "content": "Grandchild B content.",
            "children": [],
        },
    }


def _run_recursive_cli(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    max_depth: int,
    dry_run: bool = False,
    fail_on_ids: set[str] | None = None,
) -> tuple[int, Path]:
    pages = _synthetic_pages()
    fail_ids = fail_on_ids or set()

    def stub_fetch_page(target: ResolvedTarget) -> dict[str, object]:
        page_id = str(target.page_id)
        if page_id in fail_ids:
            raise RuntimeError(f"synthetic fetch failure for {page_id}")
        return dict(pages[page_id])

    monkeypatch.setattr("knowledge_adapters.confluence.client.fetch_page", stub_fetch_page)

    output_dir = tmp_path / "out"
    argv = [
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "100",
        "--output-dir",
        str(output_dir),
        "--tree",
        "--max-depth",
        str(max_depth),
    ]
    if dry_run:
        argv.append("--dry-run")

    exit_code = main(argv)
    return exit_code, output_dir


def _load_manifest(output_dir: Path) -> dict[str, object]:
    payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    return cast(dict[str, object], payload)


def _manifest_files(payload: dict[str, object]) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], payload["files"])


@pytest.mark.parametrize(
    ("max_depth", "expected_ids"),
    [
        (0, ["100"]),
        (1, ["100", "200", "300"]),
        (2, ["100", "200", "300", "205", "210"]),
    ],
)
def test_recursive_depth_semantics_are_encoded_in_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    max_depth: int,
    expected_ids: list[str],
) -> None:
    exit_code, output_dir = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=max_depth,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert payload["root_page_id"] == "100"
    assert payload["max_depth"] == max_depth
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == expected_ids


def test_recursive_run_deduplicates_by_canonical_page_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    exit_code, output_dir = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=2,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    canonical_ids = [entry["canonical_id"] for entry in _manifest_files(payload)]

    assert canonical_ids == ["100", "200", "300", "205", "210"]
    assert canonical_ids.count("200") == 1


def test_recursive_manifest_ordering_is_breadth_first_then_lexical(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    exit_code, output_dir = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=2,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "200",
        "300",
        "205",
        "210",
    ]


def test_recursive_manifest_records_root_run_context_and_current_run_files_only(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps({"generated_at": "old", "files": [{"canonical_id": "stale"}]}),
        encoding="utf-8",
    )

    exit_code, _ = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=2,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert set(payload) == {"generated_at", "root_page_id", "max_depth", "files"}
    assert payload["root_page_id"] == "100"
    assert payload["max_depth"] == 2
    assert payload["files"] == [
        {
            "canonical_id": "100",
            "source_url": "https://example.com/wiki/pages/100",
            "output_path": "pages/100.md",
            "title": "Root Page",
        },
        {
            "canonical_id": "200",
            "source_url": "https://example.com/wiki/pages/200",
            "output_path": "pages/200.md",
            "title": "Shared Child",
        },
        {
            "canonical_id": "300",
            "source_url": "https://example.com/wiki/pages/300",
            "output_path": "pages/300.md",
            "title": "Sibling Child",
        },
        {
            "canonical_id": "205",
            "source_url": "https://example.com/wiki/pages/205",
            "output_path": "pages/205.md",
            "title": "Grandchild A",
        },
        {
            "canonical_id": "210",
            "source_url": "https://example.com/wiki/pages/210",
            "output_path": "pages/210.md",
            "title": "Grandchild B",
        },
    ]


def test_recursive_run_fails_fast_without_writing_partial_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(RuntimeError, match="synthetic fetch failure for 200"):
        _run_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=2,
            fail_on_ids={"200"},
        )

    assert not (output_dir / "manifest.json").exists()


def test_recursive_dry_run_reports_unique_planned_outputs_without_writing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    exit_code, output_dir = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=2,
        dry_run=True,
    )

    assert exit_code == 0
    assert not output_dir.exists()

    captured = capsys.readouterr()
    output = captured.out

    for page_id in ["100", "200", "300", "205", "210"]:
        assert output.count(f"{output_dir / 'pages' / f'{page_id}.md'}") == 1
    assert output.count("5 unique pages") == 1
