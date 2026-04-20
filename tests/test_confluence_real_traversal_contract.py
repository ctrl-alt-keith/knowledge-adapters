from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pytest import MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.confluence.models import ResolvedTarget

ChildDiscoveryResult = list[str] | Exception


def _real_tree_argv(
    output_dir: Path,
    *,
    target: str = "100",
    max_depth: int,
) -> list[str]:
    return [
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        target,
        "--output-dir",
        str(output_dir),
        "--client-mode",
        "real",
        "--tree",
        "--max-depth",
        str(max_depth),
    ]


def _load_manifest(output_dir: Path) -> dict[str, object]:
    payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    return cast(dict[str, object], payload)


def _manifest_files(payload: dict[str, object]) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], payload["files"])


def _real_pages() -> dict[str, dict[str, object]]:
    return {
        "100": {
            "canonical_id": "100",
            "title": "Root Page",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root content.",
        },
        "200": {
            "canonical_id": "200",
            "title": "Shared Child",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Shared child content.",
        },
        "300": {
            "canonical_id": "300",
            "title": "Sibling Child",
            "source_url": "https://example.com/wiki/pages/300",
            "content": "Sibling child content.",
        },
        "205": {
            "canonical_id": "205",
            "title": "Grandchild A",
            "source_url": "https://example.com/wiki/pages/205",
            "content": "Grandchild A content.",
        },
        "210": {
            "canonical_id": "210",
            "title": "Grandchild B",
            "source_url": "https://example.com/wiki/pages/210",
            "content": "Grandchild B content.",
        },
        "400": {
            "canonical_id": "400",
            "title": "Branch B",
            "source_url": "https://example.com/wiki/pages/400",
            "content": "Branch B content.",
        },
        "500": {
            "canonical_id": "500",
            "title": "Leaf",
            "source_url": "https://example.com/wiki/pages/500",
            "content": "Leaf content.",
        },
        "900": {
            "canonical_id": "900",
            "title": "Later Grandchild",
            "source_url": "https://example.com/wiki/pages/900",
            "content": "Later grandchild content.",
        },
    }


def _real_children() -> dict[str, ChildDiscoveryResult]:
    return {
        "100": ["300", "200"],
        "200": ["205"],
        "300": ["210", "200"],
        "205": [],
        "210": [],
    }


def _called_page_id(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    candidates = list(args)
    for key in ("target", "page_id", "parent_page_id"):
        if key in kwargs:
            candidates.append(kwargs[key])

    for candidate in candidates:
        if isinstance(candidate, ResolvedTarget):
            if candidate.page_id is None:
                raise AssertionError("expected a canonical page ID")
            return candidate.page_id
        if isinstance(candidate, str):
            return candidate

    raise AssertionError("expected a canonical page ID or ResolvedTarget argument")


def _assert_no_artifacts_written(output_dir: Path) -> None:
    assert not (output_dir / "manifest.json").exists()

    pages_dir = output_dir / "pages"
    markdown_outputs = list(pages_dir.glob("*.md")) if pages_dir.exists() else []
    assert markdown_outputs == []


def _run_real_recursive_cli(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    pages: dict[str, dict[str, object]] | None = None,
    children_by_parent: dict[str, ChildDiscoveryResult] | None = None,
    target: str = "100",
    max_depth: int,
    fail_on_page_ids: set[str] | None = None,
) -> tuple[int, Path, dict[str, int], list[str]]:
    from knowledge_adapters.confluence import client as client_module

    if pages is None:
        pages = _real_pages()
    if children_by_parent is None:
        children_by_parent = _real_children()
    fail_ids = fail_on_page_ids or set()

    page_fetch_counts: dict[str, int] = {}
    child_list_calls: list[str] = []

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
    ) -> dict[str, object]:
        del base_url, auth_method

        page_id = str(target.page_id)
        page_fetch_counts[page_id] = page_fetch_counts.get(page_id, 0) + 1
        if page_id in fail_ids:
            raise RuntimeError(f"synthetic page fetch failure for {page_id}")
        return dict(pages[page_id])

    def stub_child_id_discovery(*args: object, **kwargs: object) -> list[str]:
        parent_id = _called_page_id(args, kwargs)
        child_list_calls.append(parent_id)

        result = children_by_parent[parent_id]
        if isinstance(result, Exception):
            raise result
        if not isinstance(result, list):
            raise AssertionError("child discovery results must be a list or exception")
        return [str(child_id) for child_id in result]

    def fail_if_stub_used(target: ResolvedTarget) -> dict[str, object]:
        raise AssertionError(
            f"stub client should not be used in real traversal mode for {target.page_id}"
        )

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        stub_child_id_discovery,
        raising=False,
    )
    monkeypatch.setattr(client_module, "fetch_page", fail_if_stub_used)

    output_dir = tmp_path / "out"
    exit_code = main(_real_tree_argv(output_dir, target=target, max_depth=max_depth))
    return exit_code, output_dir, page_fetch_counts, child_list_calls


@pytest.mark.parametrize(
    ("max_depth", "expected_ids", "expected_fetch_counts", "expected_child_calls"),
    [
        (0, ["100"], {"100": 1}, []),
        (1, ["100", "200", "300"], {"100": 1, "200": 1, "300": 1}, ["100"]),
        (
            2,
            ["100", "200", "300", "205", "210"],
            {"100": 1, "200": 1, "300": 1, "205": 1, "210": 1},
            ["100", "200", "300"],
        ),
    ],
)
def test_real_tree_depth_semantics_use_separate_page_fetch_and_child_discovery(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    max_depth: int,
    expected_ids: list[str],
    expected_fetch_counts: dict[str, int],
    expected_child_calls: list[str],
) -> None:
    exit_code, output_dir, page_fetch_counts, child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=max_depth,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert payload["root_page_id"] == "100"
    assert payload["max_depth"] == max_depth
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == expected_ids
    assert page_fetch_counts == expected_fetch_counts
    assert child_list_calls == expected_child_calls


def test_real_tree_orders_pages_breadth_first_then_lexical_without_parent_adjacency(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ["300", "200"],
        "200": ["900"],
        "300": ["210"],
        "210": [],
        "900": [],
    }

    exit_code, output_dir, _page_fetch_counts, child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=2,
        children_by_parent=children_by_parent,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "200",
        "300",
        "210",
        "900",
    ]
    assert child_list_calls == ["100", "200", "300"]


def test_real_tree_deduplicates_repeated_child_ids_across_levels_without_refetching(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ["300", "200", "200", "400"],
        "200": ["500", "500", "500"],
        "300": ["200", "500", "500"],
        "400": ["200", "500"],
        "500": ["200"],
    }

    exit_code, output_dir, page_fetch_counts, child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=3,
        children_by_parent=children_by_parent,
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
    assert page_fetch_counts == {
        "100": 1,
        "200": 1,
        "300": 1,
        "400": 1,
        "500": 1,
    }
    assert child_list_calls == ["100", "200", "300", "400", "500"]


def test_real_tree_stops_immediately_when_child_list_fetch_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": RuntimeError("synthetic child-list failure for 100"),
    }

    with pytest.raises(RuntimeError, match="synthetic child-list failure for 100"):
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            children_by_parent=children_by_parent,
        )

    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_immediately_on_malformed_child_list_response(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ValueError("Response error: invalid child-list payload."),
    }

    with pytest.raises(ValueError, match="invalid child-list payload"):
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            children_by_parent=children_by_parent,
        )

    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_immediately_on_missing_or_invalid_child_ids(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ValueError("Response error: invalid child page ID."),
    }

    with pytest.raises(ValueError, match="invalid child page ID"):
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            children_by_parent=children_by_parent,
        )

    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_immediately_on_descendant_page_fetch_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(RuntimeError, match="synthetic page fetch failure for 200"):
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            fail_on_page_ids={"200"},
        )

    _assert_no_artifacts_written(output_dir)
