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
    pages: dict[str, dict[str, object]] | None = None,
    target: str = "100",
    max_depth: int,
    dry_run: bool = False,
    fail_on_ids: set[str] | None = None,
) -> tuple[int, Path, dict[str, int]]:
    pages = pages or _synthetic_pages()
    fail_ids = fail_on_ids or set()
    fetch_counts: dict[str, int] = {}

    def stub_fetch_page(target: ResolvedTarget) -> dict[str, object]:
        page_id = str(target.page_id)
        fetch_counts[page_id] = fetch_counts.get(page_id, 0) + 1
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
        target,
        "--output-dir",
        str(output_dir),
        "--tree",
        "--max-depth",
        str(max_depth),
    ]
    if dry_run:
        argv.append("--dry-run")

    exit_code = main(argv)
    return exit_code, output_dir, fetch_counts


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
    exit_code, output_dir, _fetch_counts = _run_recursive_cli(
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
    exit_code, output_dir, fetch_counts = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=2,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    canonical_ids = [entry["canonical_id"] for entry in _manifest_files(payload)]

    assert canonical_ids == ["100", "200", "300", "205", "210"]
    assert canonical_ids.count("200") == 1
    assert fetch_counts["200"] == 1


def test_recursive_manifest_ordering_is_breadth_first_then_lexical(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    exit_code, output_dir, _fetch_counts = _run_recursive_cli(
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
        json.dumps(
            {
                "generated_at": "old",
                "files": [
                    {
                        "canonical_id": "stale",
                        "source_url": "https://example.com/wiki/pages/stale",
                        "output_path": "pages/stale.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code, _, _fetch_counts = _run_recursive_cli(
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
    exit_code, output_dir, _fetch_counts = _run_recursive_cli(
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


def test_recursive_deeper_tree_excludes_descendants_beyond_max_depth(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    pages: dict[str, dict[str, object]] = {
        "100": {
            "canonical_id": "100",
            "title": "Root",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root",
            "children": ["200"],
        },
        "200": {
            "canonical_id": "200",
            "title": "Depth 1",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Depth 1",
            "children": ["300"],
        },
        "300": {
            "canonical_id": "300",
            "title": "Depth 2",
            "source_url": "https://example.com/wiki/pages/300",
            "content": "Depth 2",
            "children": ["400"],
        },
        "400": {
            "canonical_id": "400",
            "title": "Depth 3",
            "source_url": "https://example.com/wiki/pages/400",
            "content": "Depth 3",
            "children": [],
        },
    }

    exit_code, output_dir, fetch_counts = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        pages=pages,
        max_depth=2,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "200",
        "300",
    ]
    assert "400" not in fetch_counts


def test_recursive_wide_tree_orders_many_siblings_lexically_within_a_depth(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    pages: dict[str, dict[str, object]] = {
        "100": {
            "canonical_id": "100",
            "title": "Root",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root",
            "children": ["450", "220", "410", "205", "330"],
        },
        "205": {
            "canonical_id": "205",
            "title": "205",
            "source_url": "https://example.com/wiki/pages/205",
            "content": "205",
            "children": [],
        },
        "220": {
            "canonical_id": "220",
            "title": "220",
            "source_url": "https://example.com/wiki/pages/220",
            "content": "220",
            "children": [],
        },
        "330": {
            "canonical_id": "330",
            "title": "330",
            "source_url": "https://example.com/wiki/pages/330",
            "content": "330",
            "children": [],
        },
        "410": {
            "canonical_id": "410",
            "title": "410",
            "source_url": "https://example.com/wiki/pages/410",
            "content": "410",
            "children": [],
        },
        "450": {
            "canonical_id": "450",
            "title": "450",
            "source_url": "https://example.com/wiki/pages/450",
            "content": "450",
            "children": [],
        },
    }

    exit_code, output_dir, _fetch_counts = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        pages=pages,
        max_depth=1,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "205",
        "220",
        "330",
        "410",
        "450",
    ]


def test_recursive_duplicate_heavy_graph_fetches_each_repeated_page_once(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    pages: dict[str, dict[str, object]] = {
        "100": {
            "canonical_id": "100",
            "title": "Root",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root",
            "children": ["300", "200", "200", "400"],
        },
        "200": {
            "canonical_id": "200",
            "title": "Shared",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Shared",
            "children": ["500", "500", "500"],
        },
        "300": {
            "canonical_id": "300",
            "title": "Branch A",
            "source_url": "https://example.com/wiki/pages/300",
            "content": "Branch A",
            "children": ["200", "500", "500"],
        },
        "400": {
            "canonical_id": "400",
            "title": "Branch B",
            "source_url": "https://example.com/wiki/pages/400",
            "content": "Branch B",
            "children": ["200", "500"],
        },
        "500": {
            "canonical_id": "500",
            "title": "Leaf",
            "source_url": "https://example.com/wiki/pages/500",
            "content": "Leaf",
            "children": [],
        },
    }

    exit_code, output_dir, fetch_counts = _run_recursive_cli(
        tmp_path,
        monkeypatch,
        pages=pages,
        max_depth=2,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "200",
        "300",
        "400",
        "500",
    ]
    assert fetch_counts["200"] == 1
    assert fetch_counts["500"] == 1
