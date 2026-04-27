from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pytest import CaptureFixture, MonkeyPatch

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


def _real_space_argv(
    output_dir: Path,
    *,
    space_flag: str = "--space-key",
    space_value: str = "ENG",
) -> list[str]:
    return [
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        space_flag,
        space_value,
        "--output-dir",
        str(output_dir),
        "--client-mode",
        "real",
    ]


def _load_manifest(output_dir: Path) -> dict[str, object]:
    payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    return cast(dict[str, object], payload)


def _manifest_files(payload: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], payload["files"])


def _write_previous_manifest(output_dir: Path, files: list[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-19T00:00:00Z",
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _real_pages() -> dict[str, dict[str, object]]:
    return {
        "100": {
            "canonical_id": "100",
            "title": "Root Page",
            "source_url": "https://example.com/wiki/pages/100",
            "content": "Root content.",
            "page_version": 1,
            "last_modified": "2026-04-20T00:00:00Z",
        },
        "200": {
            "canonical_id": "200",
            "title": "Shared Child",
            "source_url": "https://example.com/wiki/pages/200",
            "content": "Shared child content.",
            "page_version": 2,
            "last_modified": "2026-04-20T00:01:00Z",
        },
        "300": {
            "canonical_id": "300",
            "title": "Sibling Child",
            "source_url": "https://example.com/wiki/pages/300",
            "content": "Sibling child content.",
            "page_version": 3,
            "last_modified": "2026-04-20T00:02:00Z",
        },
        "205": {
            "canonical_id": "205",
            "title": "Grandchild A",
            "source_url": "https://example.com/wiki/pages/205",
            "content": "Grandchild A content.",
            "page_version": 4,
            "last_modified": "2026-04-20T00:03:00Z",
        },
        "210": {
            "canonical_id": "210",
            "title": "Grandchild B",
            "source_url": "https://example.com/wiki/pages/210",
            "content": "Grandchild B content.",
            "page_version": 5,
            "last_modified": "2026-04-20T00:04:00Z",
        },
        "400": {
            "canonical_id": "400",
            "title": "Branch B",
            "source_url": "https://example.com/wiki/pages/400",
            "content": "Branch B content.",
            "page_version": 6,
            "last_modified": "2026-04-20T00:05:00Z",
        },
        "500": {
            "canonical_id": "500",
            "title": "Leaf",
            "source_url": "https://example.com/wiki/pages/500",
            "content": "Leaf content.",
            "page_version": 7,
            "last_modified": "2026-04-20T00:06:00Z",
        },
        "900": {
            "canonical_id": "900",
            "title": "Later Grandchild",
            "source_url": "https://example.com/wiki/pages/900",
            "content": "Later grandchild content.",
            "page_version": 8,
            "last_modified": "2026-04-20T00:07:00Z",
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


def _assert_concise_cli_error(
    capsys: CaptureFixture[str],
    *,
    expected_message: str,
) -> None:
    captured = capsys.readouterr()
    assert (
        captured.err
        == f"knowledge-adapters confluence: error: {expected_message}\n"
    )


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
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file

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


def _run_real_space_cli(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    pages: dict[str, dict[str, object]] | None = None,
    discovered_page_ids: list[str] | None = None,
    space_flag: str = "--space-key",
    space_value: str = "ENG",
) -> tuple[int, Path, dict[str, int], list[str]]:
    from knowledge_adapters.confluence import client as client_module

    if pages is None:
        pages = _real_pages()
    if discovered_page_ids is None:
        discovered_page_ids = ["300", "100", "200"]

    page_fetch_counts: dict[str, int] = {}
    space_list_calls: list[str] = []

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file

        page_id = str(target.page_id)
        page_fetch_counts[page_id] = page_fetch_counts.get(page_id, 0) + 1
        return dict(pages[page_id])

    def stub_space_discovery(
        space_key: str,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> list[str]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        space_list_calls.append(space_key)
        return list(discovered_page_ids or [])

    def fail_if_child_discovery_used(*args: object, **kwargs: object) -> list[str]:
        del args, kwargs
        raise AssertionError("child discovery should not be used in space mode")

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_space_page_ids",
        stub_space_discovery,
        raising=False,
    )
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        fail_if_child_discovery_used,
        raising=False,
    )

    output_dir = tmp_path / "out"
    exit_code = main(
        _real_space_argv(
            output_dir,
            space_flag=space_flag,
            space_value=space_value,
        )
    )
    return exit_code, output_dir, page_fetch_counts, space_list_calls


@pytest.mark.parametrize(
    ("space_flag", "space_value"),
    [
        ("--space-key", "ENG"),
        ("--space-url", "https://example.com/wiki/spaces/ENG/overview"),
    ],
)
def test_real_space_mode_discovers_pages_and_writes_in_lexical_order(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    space_flag: str,
    space_value: str,
) -> None:
    exit_code, output_dir, page_fetch_counts, space_list_calls = _run_real_space_cli(
        tmp_path,
        monkeypatch,
        discovered_page_ids=["300", "100", "200", "100"],
        space_flag=space_flag,
        space_value=space_value,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert "root_page_id" not in payload
    assert "max_depth" not in payload
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "200",
        "300",
    ]
    assert page_fetch_counts == {"100": 1, "200": 1, "300": 1}
    assert space_list_calls == ["ENG"]

    output = capsys.readouterr().out
    assert "mode: space" not in output
    assert "fetch_scope: space" in output
    assert "space_key: ENG" in output
    assert "pages_discovered: 3" in output
    assert "pages_planned: 3" in output
    assert "Summary: wrote 3, skipped 0" in output


def test_real_tree_runs_without_traversal_cache_by_default(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    exit_code, _output_dir, _page_fetch_counts, child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=1,
    )

    assert exit_code == 0
    assert child_list_calls == ["100"]
    output = capsys.readouterr().out
    assert "tree_cache_hits" not in output
    assert "tree_cache_misses" not in output


def test_real_tree_reuses_cached_child_page_listing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    pages = _real_pages()
    cache_dir = tmp_path / "cache"
    child_list_calls: list[str] = []

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        return dict(pages[str(target.page_id)])

    def stub_child_id_discovery(*args: object, **kwargs: object) -> list[str]:
        parent_id = _called_page_id(args, kwargs)
        child_list_calls.append(parent_id)
        return ["200", "300"]

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        stub_child_id_discovery,
        raising=False,
    )

    first_output_dir = tmp_path / "first"
    assert (
        main(
            [
                *_real_tree_argv(first_output_dir, max_depth=1),
                "--tree-cache-dir",
                str(cache_dir),
            ]
        )
        == 0
    )
    first_output = capsys.readouterr().out
    assert "tree_cache_hits: 0" in first_output
    assert "tree_cache_misses: 1" in first_output

    second_output_dir = tmp_path / "second"
    assert (
        main(
            [
                *_real_tree_argv(second_output_dir, max_depth=1),
                "--tree-cache-dir",
                str(cache_dir),
            ]
        )
        == 0
    )

    assert child_list_calls == ["100"]
    second_output = capsys.readouterr().out
    assert "tree_cache_hits: 1" in second_output
    assert "tree_cache_misses: 0" in second_output


def test_real_tree_cache_write_failure_does_not_fail_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module
    from knowledge_adapters.confluence.tree_cache import ConfluenceTreeCache

    pages = _real_pages()
    child_list_calls: list[str] = []

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        return dict(pages[str(target.page_id)])

    def stub_child_id_discovery(*args: object, **kwargs: object) -> list[str]:
        parent_id = _called_page_id(args, kwargs)
        child_list_calls.append(parent_id)
        return ["200", "300"]

    def raise_write_error(
        self: ConfluenceTreeCache,
        *,
        kind: str,
        key_value: str,
        entry: object,
    ) -> None:
        del self, kind, key_value, entry
        raise OSError("synthetic write failure")

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        stub_child_id_discovery,
        raising=False,
    )
    monkeypatch.setattr(ConfluenceTreeCache, "_write_entry", raise_write_error)

    assert (
        main(
            [
                *_real_tree_argv(tmp_path / "out", max_depth=1),
                "--tree-cache-dir",
                str(tmp_path / "cache"),
            ]
        )
        == 0
    )

    assert child_list_calls == ["100"]
    output = capsys.readouterr().out
    assert "Summary: wrote 3, skipped 0" in output
    assert "tree_cache_hits: 0" in output
    assert "tree_cache_misses: 1" in output


def test_real_space_reuses_cached_space_page_listing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    pages = _real_pages()
    cache_dir = tmp_path / "cache"
    space_list_calls: list[str] = []

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        return dict(pages[str(target.page_id)])

    def stub_space_discovery(
        space_key: str,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> list[str]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        space_list_calls.append(space_key)
        return ["300", "100", "200"]

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_space_page_ids",
        stub_space_discovery,
        raising=False,
    )

    first_output_dir = tmp_path / "first"
    assert (
        main(
            [
                *_real_space_argv(first_output_dir),
                "--tree-cache-dir",
                str(cache_dir),
            ]
        )
        == 0
    )
    first_output = capsys.readouterr().out
    assert "tree_cache_hits: 0" in first_output
    assert "tree_cache_misses: 1" in first_output

    second_output_dir = tmp_path / "second"
    assert (
        main(
            [
                *_real_space_argv(second_output_dir),
                "--tree-cache-dir",
                str(cache_dir),
            ]
        )
        == 0
    )

    assert space_list_calls == ["ENG"]
    second_output = capsys.readouterr().out
    assert "tree_cache_hits: 1" in second_output
    assert "tree_cache_misses: 0" in second_output


def test_real_space_dry_run_reports_space_summary_and_planned_actions(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    pages = _real_pages()

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        return dict(pages[str(target.page_id)])

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_space_page_ids",
        lambda space_key, **kwargs: ["200", "100"] if space_key == "ENG" else [],
        raising=False,
    )

    output_dir = tmp_path / "out"
    exit_code = main([*_real_space_argv(output_dir), "--dry-run"])

    assert exit_code == 0
    assert not (output_dir / "manifest.json").exists()

    output = capsys.readouterr().out
    assert "mode: space" in output
    assert "space_key: ENG" in output
    assert "pages_discovered: 2" in output
    assert "pages_in_plan: 2" in output
    assert "would_write: 2" in output
    assert "would write " in output
    assert "pages/100.md" in output
    assert "pages/200.md" in output


@pytest.mark.parametrize(
    ("extra_args", "expected_message"),
    [
        ([], "space mode requires --client-mode real"),
        (
            ["--client-mode", "real", "--target", "100"],
            "space mode cannot be combined with --target.",
        ),
        (
            ["--client-mode", "real", "--tree"],
            "space mode cannot be combined with --tree.",
        ),
        (
            ["--client-mode", "real", "--max-depth", "1"],
            "space mode cannot be combined with --max-depth.",
        ),
        (
            ["--client-mode", "real", "--space-url", "https://example.com/wiki/spaces/ENG/overview"],
            "--space-key and --space-url are mutually exclusive.",
        ),
    ],
)
def test_space_mode_rejects_invalid_cli_combinations(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    extra_args: list[str],
    expected_message: str,
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--space-key",
                "ENG",
                "--output-dir",
                str(output_dir),
                *extra_args,
            ]
        )

    assert exc_info.value.code == 2
    _assert_concise_cli_error(capsys, expected_message=expected_message)
    _assert_no_artifacts_written(output_dir)


def test_space_mode_rejects_invalid_space_url_shape(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            _real_space_argv(
                output_dir,
                space_flag="--space-url",
                space_value="https://example.com/wiki/spaces/ENG/pages",
            )
        )

    assert exc_info.value.code == 2
    _assert_concise_cli_error(
        capsys,
        expected_message=(
            "--space-url 'https://example.com/wiki/spaces/ENG/pages' must match "
            "/spaces/{SPACE}/overview."
        ),
    )
    _assert_no_artifacts_written(output_dir)


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


def test_real_tree_incremental_run_skips_full_page_fetch_for_unchanged_pages(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    output_dir = tmp_path / "out"
    pages = _real_pages()
    _write_previous_manifest(
        output_dir,
        [
            {
                "canonical_id": "100",
                "source_url": pages["100"]["source_url"],
                "output_path": "pages/100.md",
                "title": pages["100"]["title"],
                "page_version": pages["100"]["page_version"],
                "last_modified": pages["100"]["last_modified"],
            },
            {
                "canonical_id": "200",
                "source_url": pages["200"]["source_url"],
                "output_path": "pages/200.md",
                "title": pages["200"]["title"],
                "page_version": pages["200"]["page_version"],
                "last_modified": pages["200"]["last_modified"],
            },
        ],
    )
    for page_id in ("100", "200"):
        page_path = output_dir / "pages" / f"{page_id}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(f"existing {page_id}\n", encoding="utf-8")

    full_fetch_counts: dict[str, int] = {}
    summary_fetch_counts: dict[str, int] = {}

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        page_id = str(target.page_id)
        full_fetch_counts[page_id] = full_fetch_counts.get(page_id, 0) + 1
        return dict(pages[page_id])

    def stub_real_fetch_summary(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file
        page_id = str(target.page_id)
        summary_fetch_counts[page_id] = summary_fetch_counts.get(page_id, 0) + 1
        page = dict(pages[page_id])
        page.pop("content", None)
        return page

    def stub_child_id_discovery(*args: object, **kwargs: object) -> list[str]:
        parent_id = _called_page_id(args, kwargs)
        result = _real_children()[parent_id]
        if isinstance(result, Exception):
            raise result
        return [str(child_id) for child_id in result]

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "fetch_real_page_summary",
        stub_real_fetch_summary,
        raising=False,
    )
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        stub_child_id_discovery,
        raising=False,
    )

    exit_code = main(_real_tree_argv(output_dir, max_depth=1))

    assert exit_code == 0
    assert full_fetch_counts == {"300": 1}
    assert summary_fetch_counts == {"100": 1, "200": 1, "300": 1}

    captured = capsys.readouterr()
    assert "Skipped: " in captured.out
    assert "Wrote: " in captured.out
    assert "new_pages: 1" in captured.out
    assert "changed_pages: 0" in captured.out
    assert "unchanged_pages: 2" in captured.out
    assert "Tree fetch progress: fetched 0/1, skipped 2, planned 3" in captured.out
    assert "Tree fetch progress: fetched 1/1, skipped 2, planned 3" in captured.out


def test_real_tree_run_does_not_report_stub_discovery_limit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    exit_code, _output_dir, _page_fetch_counts, _child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=1,
    )

    assert exit_code == 0

    output = capsys.readouterr().out
    assert "client_mode: real" in output
    assert (
        "note: stub mode does not support descendant discovery; use --client-mode real "
        "to discover descendants from Confluence."
    ) not in output


def test_real_tree_reports_depth_progress_during_traversal(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    exit_code, _output_dir, _page_fetch_counts, _child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=2,
    )

    assert exit_code == 0

    output = capsys.readouterr().out
    assert "Tree progress: traversal started, max_depth 2" in output
    assert "Tree progress: depth 0, discovered 1, fetched 1, planned 1" in output
    assert "Tree progress: depth 1, discovered 3, fetched 3, planned 3" in output
    assert "Tree progress: depth 2, discovered 5, fetched 5, planned 5" in output


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


def test_real_tree_depth_one_does_not_query_descendant_child_lists(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ["300", "200"],
        "200": RuntimeError("child list for 200 should not be queried at depth 1"),
        "300": RuntimeError("child list for 300 should not be queried at depth 1"),
    }

    exit_code, output_dir, page_fetch_counts, child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        max_depth=1,
        children_by_parent=children_by_parent,
    )

    assert exit_code == 0

    payload = _load_manifest(output_dir)
    assert [entry["canonical_id"] for entry in _manifest_files(payload)] == [
        "100",
        "200",
        "300",
    ]
    assert page_fetch_counts == {"100": 1, "200": 1, "300": 1}
    assert child_list_calls == ["100"]


def test_real_tree_unsorted_duplicate_heavy_inputs_still_produce_deterministic_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    pages: dict[str, dict[str, object]] = {
        **_real_pages(),
        "220": {
            "canonical_id": "220",
            "title": "220",
            "source_url": "https://example.com/wiki/pages/220",
            "content": "220 content.",
        },
        "330": {
            "canonical_id": "330",
            "title": "330",
            "source_url": "https://example.com/wiki/pages/330",
            "content": "330 content.",
        },
        "410": {
            "canonical_id": "410",
            "title": "410",
            "source_url": "https://example.com/wiki/pages/410",
            "content": "410 content.",
        },
        "450": {
            "canonical_id": "450",
            "title": "450",
            "source_url": "https://example.com/wiki/pages/450",
            "content": "450 content.",
        },
        "600": {
            "canonical_id": "600",
            "title": "600",
            "source_url": "https://example.com/wiki/pages/600",
            "content": "600 content.",
        },
        "700": {
            "canonical_id": "700",
            "title": "700",
            "source_url": "https://example.com/wiki/pages/700",
            "content": "700 content.",
        },
    }
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ["450", "220", "410", "205", "330", "220", "410"],
        "205": ["600", "500", "500", "700"],
        "220": ["700", "600", "500", "700"],
        "330": ["500", "700", "600", "500"],
        "410": [],
        "450": [],
        "500": [],
        "600": [],
        "700": [],
    }

    exit_code, output_dir, page_fetch_counts, child_list_calls = _run_real_recursive_cli(
        tmp_path,
        monkeypatch,
        pages=pages,
        max_depth=2,
        children_by_parent=children_by_parent,
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
        "500",
        "600",
        "700",
    ]
    assert page_fetch_counts == {
        "100": 1,
        "205": 1,
        "220": 1,
        "330": 1,
        "410": 1,
        "450": 1,
        "500": 1,
        "600": 1,
        "700": 1,
    }
    assert child_list_calls == ["100", "205", "220", "330", "410", "450"]


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
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": RuntimeError("synthetic child-list failure for 100"),
    }

    with pytest.raises(SystemExit) as exc_info:
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            children_by_parent=children_by_parent,
        )

    assert exc_info.value.code == 2
    _assert_concise_cli_error(
        capsys,
        expected_message="synthetic child-list failure for 100",
    )
    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_immediately_on_malformed_child_list_response(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ValueError("Response error: invalid child-list payload."),
    }

    with pytest.raises(SystemExit) as exc_info:
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            children_by_parent=children_by_parent,
        )

    assert exc_info.value.code == 2
    _assert_concise_cli_error(
        capsys,
        expected_message="Response error: invalid child-list payload.",
    )
    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_without_writes_when_later_child_list_fails_after_partial_discovery(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    page_fetch_counts: dict[str, int] = {}
    child_list_calls: list[str] = []

    pages = _real_pages()
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ["300", "200"],
        "200": [],
        "300": RuntimeError("synthetic child-list failure for 300"),
    }

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file

        page_id = str(target.page_id)
        page_fetch_counts[page_id] = page_fetch_counts.get(page_id, 0) + 1
        return dict(pages[page_id])

    def stub_child_id_discovery(*args: object, **kwargs: object) -> list[str]:
        parent_id = _called_page_id(args, kwargs)
        child_list_calls.append(parent_id)

        result = children_by_parent[parent_id]
        if isinstance(result, Exception):
            raise result
        return [str(child_id) for child_id in result]

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        stub_child_id_discovery,
        raising=False,
    )

    output_dir = tmp_path / "out"
    with pytest.raises(SystemExit) as exc_info:
        main(_real_tree_argv(output_dir, max_depth=2))

    assert exc_info.value.code == 2
    assert page_fetch_counts == {"100": 1, "200": 1, "300": 1}
    assert child_list_calls == ["100", "200", "300"]
    _assert_concise_cli_error(
        capsys,
        expected_message="synthetic child-list failure for 300",
    )
    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_immediately_on_missing_or_invalid_child_ids(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    children_by_parent: dict[str, ChildDiscoveryResult] = {
        "100": ValueError("Response error: invalid child page ID."),
    }

    with pytest.raises(SystemExit) as exc_info:
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            children_by_parent=children_by_parent,
        )

    assert exc_info.value.code == 2
    _assert_concise_cli_error(
        capsys,
        expected_message="Response error: invalid child page ID.",
    )
    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_without_writes_when_later_page_fetch_fails_after_partial_success(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    page_fetch_counts: dict[str, int] = {}
    child_list_calls: list[str] = []

    pages = _real_pages()

    def stub_real_fetch(
        target: ResolvedTarget,
        *,
        base_url: str = "https://example.com/wiki",
        auth_method: str = "bearer-env",
        ca_bundle: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
    ) -> dict[str, object]:
        del base_url, auth_method, ca_bundle, client_cert_file, client_key_file

        page_id = str(target.page_id)
        page_fetch_counts[page_id] = page_fetch_counts.get(page_id, 0) + 1
        if page_id == "300":
            raise RuntimeError("synthetic page fetch failure for 300")
        return dict(pages[page_id])

    def stub_child_id_discovery(*args: object, **kwargs: object) -> list[str]:
        parent_id = _called_page_id(args, kwargs)
        child_list_calls.append(parent_id)
        if parent_id == "100":
            return ["300", "200"]
        return []

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(
        client_module,
        "list_real_child_page_ids",
        stub_child_id_discovery,
        raising=False,
    )

    output_dir = tmp_path / "out"
    with pytest.raises(SystemExit) as exc_info:
        main(_real_tree_argv(output_dir, max_depth=1))

    assert exc_info.value.code == 2
    assert page_fetch_counts == {"100": 1, "200": 1, "300": 1}
    assert child_list_calls == ["100"]
    _assert_concise_cli_error(
        capsys,
        expected_message="synthetic page fetch failure for 300",
    )
    _assert_no_artifacts_written(output_dir)


def test_real_tree_stops_immediately_on_descendant_page_fetch_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        _run_real_recursive_cli(
            tmp_path,
            monkeypatch,
            max_depth=1,
            fail_on_page_ids={"200"},
        )

    assert exc_info.value.code == 2
    _assert_concise_cli_error(
        capsys,
        expected_message="synthetic page fetch failure for 200",
    )
    _assert_no_artifacts_written(output_dir)
