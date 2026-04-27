import io
from pathlib import Path

import pytest
from pytest import CaptureFixture

from knowledge_adapters.cli import _ProgressAwareStream, _ProgressLineRenderer, main
from tests.artifact_assertions import assert_manifest_entries, manifest_file
from tests.cli_output_assertions import (
    assert_dry_run_summary,
    assert_tree_plan_page_count,
    assert_write_summary,
)


class _TTYStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_progress_line_renderer_reuses_one_tty_line_until_finished() -> None:
    stream = _TTYStringIO()
    renderer = _ProgressLineRenderer(stream)

    renderer.render("discovered_pages: 500")
    renderer.render("discovered_pages: 1000")
    renderer.finish()

    assert stream.getvalue() == "\rdiscovered_pages: 500\rdiscovered_pages: 1000\n"


def test_progress_aware_stream_finishes_active_tty_progress_once_before_output() -> None:
    stream = _TTYStringIO()
    renderer = _ProgressLineRenderer(stream)
    progress_stream = _ProgressAwareStream(stream, renderer)

    renderer.render("discovered_pages: 1000")
    print(
        "Tree progress: depth 1, discovered 1001, fetched 1001, planned 1001",
        file=progress_stream,
    )

    assert (
        stream.getvalue()
        == "\rdiscovered_pages: 1000\n"
        "Tree progress: depth 1, discovered 1001, fetched 1001, planned 1001\n"
    )


def test_progress_line_renderer_clears_shorter_tty_updates() -> None:
    stream = _TTYStringIO()
    renderer = _ProgressLineRenderer(stream)

    renderer.render("discovered_pages: 1000")
    renderer.render("done")
    renderer.finish()

    assert stream.getvalue() == "\rdiscovered_pages: 1000\rdone                  \n"


def test_confluence_cli_dry_run_reports_output_without_writing(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            "12345",
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0

    output_path = output_dir / "pages" / "12345.md"
    assert not output_path.exists()
    assert not (output_dir / "manifest.json").exists()

    captured = capsys.readouterr()
    assert "Confluence adapter invoked" in captured.out
    assert "client_mode: stub" in captured.out
    assert "content_source: scaffolded page content" in captured.out
    assert "mode: single" in captured.out
    assert "run_mode: dry-run" in captured.out
    assert "Plan: Confluence run" in captured.out
    assert "resolved_page_id: 12345" in captured.out
    assert "source_url: https://example.com/wiki/pages/viewpage.action?pageId=12345" in captured.out
    assert f"Artifact: {output_path}" in captured.out
    assert f"Manifest: {output_dir / 'manifest.json'}" in captured.out
    assert "planned_action: would write" in captured.out
    assert_dry_run_summary(captured.out, would_write=1, would_skip=0)
    assert "# stub-page-12345" in captured.out


def test_confluence_cli_dry_run_reports_same_resolved_target_details_for_full_url_input(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            "https://example.com/wiki/spaces/ENG/pages/12345/Runbook",
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert "resolved_page_id: 12345" in captured.out
    assert "source_url: https://example.com/wiki/pages/viewpage.action?pageId=12345" in captured.out
    assert f"Artifact: {output_dir / 'pages' / '12345.md'}" in captured.out
    assert (
        "- source_url: https://example.com/wiki/pages/viewpage.action?pageId=12345" in captured.out
    )


def test_confluence_cli_writes_manifest_for_normal_run(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            "12345",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0

    assert_manifest_entries(
        output_dir / "manifest.json",
        files=[
            manifest_file(
                canonical_id="12345",
                source_url="https://example.com/wiki/pages/viewpage.action?pageId=12345",
                output_path="pages/12345.md",
                title="stub-page-12345",
                page_version=1,
                last_modified="1970-01-01T00:00:00Z",
            )
        ],
    )


def test_confluence_cli_renders_symlinked_output_paths_consistently(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    alias_root = tmp_path / "alias"
    try:
        alias_root.symlink_to(real_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    output_dir_arg = alias_root / "out"
    resolved_output_dir = (real_root / "out").resolve()

    exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            "12345",
            "--output-dir",
            str(output_dir_arg),
        ]
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert f"output_dir: {resolved_output_dir}" in captured.out
    assert f"Artifact: {resolved_output_dir / 'pages' / '12345.md'}" in captured.out
    assert f"Wrote: {resolved_output_dir / 'pages' / '12345.md'}" in captured.out
    assert f"Manifest: {resolved_output_dir / 'manifest.json'}" in captured.out
    assert f"Write complete. Artifacts created under {resolved_output_dir}" in captured.out


def test_confluence_cli_full_flow_keeps_dry_run_and_write_artifacts_in_sync(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"
    target_url = "https://example.com/wiki/spaces/ENG/pages/12345/Runbook"
    page_output_path = output_dir / "pages" / "12345.md"
    manifest_output_path = output_dir / "manifest.json"
    canonical_source_url = "https://example.com/wiki/pages/viewpage.action?pageId=12345"

    dry_run_exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            target_url,
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert dry_run_exit_code == 0
    assert not page_output_path.exists()
    assert not manifest_output_path.exists()

    dry_run_output = capsys.readouterr().out
    assert "client_mode: stub" in dry_run_output
    assert "content_source: scaffolded page content" in dry_run_output
    assert "mode: single" in dry_run_output
    assert "run_mode: dry-run" in dry_run_output
    assert "Plan: Confluence run" in dry_run_output
    assert "resolved_page_id: 12345" in dry_run_output
    assert f"source_url: {canonical_source_url}" in dry_run_output
    assert f"Artifact: {page_output_path}" in dry_run_output
    assert f"Manifest: {manifest_output_path}" in dry_run_output
    assert "planned_action: would write" in dry_run_output
    assert_dry_run_summary(dry_run_output, would_write=1, would_skip=0)

    write_exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            target_url,
            "--output-dir",
            str(output_dir),
        ]
    )

    assert write_exit_code == 0
    assert page_output_path.exists()
    assert manifest_output_path.exists()

    write_output = capsys.readouterr().out
    assert "client_mode: stub" in write_output
    assert "content_source: scaffolded page content" in write_output
    assert "fetch_scope: page" in write_output
    assert "run_mode: write" in write_output
    assert "Plan: Confluence run" in write_output
    assert "resolved_page_id: 12345" in write_output
    assert f"Artifact: {page_output_path}" in write_output
    assert f"Manifest: {manifest_output_path}" in write_output
    assert "planned_action: write" in write_output
    assert f"Wrote: {page_output_path}" in write_output
    assert_write_summary(write_output, wrote=1, skipped=0)
    assert f"Manifest: {manifest_output_path}" in write_output
    assert f"Write complete. Artifacts created under {output_dir}" in write_output

    assert_manifest_entries(
        manifest_output_path,
        files=[
            manifest_file(
                canonical_id="12345",
                source_url=canonical_source_url,
                output_path="pages/12345.md",
                title="stub-page-12345",
                page_version=1,
                last_modified="1970-01-01T00:00:00Z",
            )
        ],
    )


def test_confluence_cli_tree_run_reports_manifest_path(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            "12345",
            "--output-dir",
            str(output_dir),
            "--tree",
            "--max-depth",
            "0",
        ]
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert "fetch_scope: tree" in captured.out
    assert "max_depth: 0" in captured.out
    assert f"Manifest: {output_dir / 'manifest.json'}" in captured.out


def test_confluence_cli_tree_dry_run_reports_manifest_path(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "confluence",
            "--base-url",
            "https://example.com/wiki",
            "--target",
            "12345",
            "--output-dir",
            str(output_dir),
            "--tree",
            "--max-depth",
            "0",
            "--dry-run",
        ]
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert "mode: tree" in captured.out
    assert "max_depth: 0 (root only)" in captured.out
    assert f"Manifest: {output_dir / 'manifest.json'}" in captured.out
    assert "Plan: Confluence run" in captured.out
    assert_tree_plan_page_count(captured.out, count=1)
    assert_dry_run_summary(captured.out, would_write=1, would_skip=0)


def test_confluence_cli_invalid_target_reports_expected_shapes(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "not-a-page",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        "knowledge-adapters confluence: error: Could not resolve target "
        "'not-a-page'. Provide a numeric page ID or full Confluence page URL.\n"
    ) in captured.err


def test_confluence_cli_rejects_empty_target(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "   ",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        "knowledge-adapters confluence: error: --target cannot be empty. "
        "Provide a page ID or full Confluence page URL.\n"
    ) in captured.err


def test_confluence_cli_rejects_malformed_target_url(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "https:///pages/viewpage.action?pageId=12345",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        "knowledge-adapters confluence: error: Target URL "
        "'https:///pages/viewpage.action?pageId=12345' is malformed. "
        "Provide a full Confluence page URL or page ID.\n"
    ) in captured.err


def test_confluence_cli_rejects_target_url_outside_base_url(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "https://other.example.com/wiki/spaces/ENG/pages/12345/Runbook",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        "knowledge-adapters confluence: error: Target URL "
        "'https://other.example.com/wiki/spaces/ENG/pages/12345/Runbook' does not "
        "match --base-url 'https://example.com/wiki'. Use a URL under that base URL "
        "or pass the page ID directly.\n"
    ) in captured.err


def test_confluence_cli_rejects_unknown_auth_method_with_supported_values(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str(output_dir),
                "--auth-method",
                "not-real",
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        "argument --auth-method: unsupported value 'not-real'. Choose "
        "'bearer-env' or 'client-cert-env'.\n" in captured.err
    )


def test_confluence_cli_rejects_negative_max_depth(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str(output_dir),
                "--tree",
                "--max-depth",
                "-1",
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        "knowledge-adapters confluence: error: --max-depth must be greater than or equal to 0.\n"
    ) in captured.err


def test_confluence_cli_requires_tree_when_max_depth_is_explicit(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str(output_dir),
                "--max-depth",
                "1",
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert "knowledge-adapters confluence: error: --max-depth requires --tree.\n" in captured.err


def test_confluence_cli_reports_invalid_output_dir(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_path = tmp_path / "artifacts.txt"
    output_path.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str(output_path),
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert f"Output path is not a directory: {output_path}." in captured.err
    assert "Verify --output-dir and use a directory path." in captured.err
