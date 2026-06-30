import json
from pathlib import Path

import pytest
from pytest import CaptureFixture

from knowledge_adapters.cli import main
from knowledge_adapters.local_files.client import fetch_file
from knowledge_adapters.local_files.normalize import normalize_to_markdown
from tests.artifact_assertions import (
    assert_manifest_entries,
    assert_markdown_document,
    manifest_file,
)
from tests.cli_output_assertions import assert_orphaned_artifacts


def test_fetch_file_reads_local_path_into_adapter_payload(tmp_path: Path) -> None:
    source_file = tmp_path / "notes.txt"
    source_file.write_text("Hello from disk.\n", encoding="utf-8")

    payload = fetch_file(str(source_file))

    assert payload == {
        "title": "notes.txt",
        "canonical_id": str(source_file.resolve()),
        "source_url": source_file.resolve().as_uri(),
        "content": "Hello from disk.\n",
        "source": "local_files",
        "adapter": "local_files",
    }


def test_local_files_reuses_shared_normalizer() -> None:
    markdown = normalize_to_markdown(
        {
            "title": "notes.txt",
            "canonical_id": "/tmp/notes.txt",
            "source_url": "file:///tmp/notes.txt",
            "content": "Hello from disk.",
            "source": "local_files",
            "adapter": "local_files",
        }
    )

    assert_markdown_document(
        markdown,
        title="notes.txt",
        metadata={
            "source": "local_files",
            "canonical_id": "/tmp/notes.txt",
            "parent_id": "",
            "source_url": "file:///tmp/notes.txt",
            "fetched_at": "",
            "updated_at": "",
            "adapter": "local_files",
        },
        content="Hello from disk.",
    )


def test_local_files_cli_writes_normalized_markdown(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "meeting-notes.txt"
    source_file.write_text("Line one.\nLine two.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(source_file),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Summary: wrote 1, skipped 0" in captured.out
    assert f"Artifact path: {output_dir / 'pages' / 'meeting-notes.md'}" in captured.out
    assert f"Manifest path: {output_dir / 'manifest.json'}" in captured.out

    output_path = output_dir / "pages" / "meeting-notes.md"
    assert output_path.exists()
    assert_markdown_document(
        output_path.read_text(encoding="utf-8"),
        title="meeting-notes.txt",
        metadata={
            "source": "local_files",
            "canonical_id": str(source_file.resolve()),
            "parent_id": "",
            "source_url": source_file.resolve().as_uri(),
            "fetched_at": "",
            "updated_at": "",
            "adapter": "local_files",
        },
        content="Line one.\nLine two.",
    )

    assert_manifest_entries(
        output_dir / "manifest.json",
        files=[
            manifest_file(
                canonical_id=str(source_file.resolve()),
                source_url=source_file.resolve().as_uri(),
                output_path="pages/meeting-notes.md",
                title="meeting-notes.txt",
            )
        ],
    )


def test_local_files_cli_dry_run_reports_output_without_writing(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "meeting-notes.txt"
    source_file.write_text("Line one.\nLine two.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(source_file),
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0

    output_path = output_dir / "pages" / "meeting-notes.md"
    assert not output_path.exists()
    assert not (output_dir / "manifest.json").exists()

    captured = capsys.readouterr()
    assert "Local files adapter invoked" in captured.out
    assert "run_mode: dry-run" in captured.out
    assert "Plan: Local files run" in captured.out
    assert f"resolved_file_path: {source_file.resolve()}" in captured.out
    assert f"source_url: {source_file.resolve().as_uri()}" in captured.out
    assert f"Artifact path: {output_path}" in captured.out
    assert f"Manifest path: {output_dir / 'manifest.json'}" in captured.out
    assert "content_status: UTF-8 text with content" in captured.out
    assert "action: would write" in captured.out
    assert "Summary: would write 1, would skip 0" in captured.out
    assert "Dry run complete. No files written." in captured.out
    assert "Line one." in captured.out


def test_local_files_cli_renders_symlinked_paths_consistently(
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

    source_file = real_root / "meeting-notes.txt"
    source_file.write_text("Line one.\nLine two.\n", encoding="utf-8")
    file_path_arg = alias_root / "meeting-notes.txt"
    output_dir_arg = alias_root / "out"
    resolved_output_dir = (real_root / "out").resolve()

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(file_path_arg),
            "--output-dir",
            str(output_dir_arg),
            "--dry-run",
        ]
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert f"file_path: {source_file.resolve()}" in captured.out
    assert f"output_dir: {resolved_output_dir}" in captured.out
    assert f"resolved_file_path: {source_file.resolve()}" in captured.out
    assert f"Artifact path: {resolved_output_dir / 'pages' / 'meeting-notes.md'}" in captured.out
    assert f"Manifest path: {resolved_output_dir / 'manifest.json'}" in captured.out


def test_local_files_cli_fails_fast_for_same_stem_artifact_collision(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    first_source = tmp_path / "notes.txt"
    first_source.write_text("First file.\n", encoding="utf-8")
    second_source = tmp_path / "notes.md"
    second_source.write_text("Second file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(first_source),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "local_files",
                "--file-path",
                str(second_source),
                "--output-dir",
                str(output_dir),
                "--dry-run",
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "knowledge-adapters local_files: error:" in captured.err
    assert f"Artifact path collision: {output_dir / 'pages' / 'notes.md'}" in captured.err
    assert f"source file {first_source.resolve()}" in captured.err
    assert f"this run resolves {second_source.resolve()}." in captured.err
    assert "Remove or rename one of the source files" in captured.err
    manifest_payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["files"][0]["canonical_id"] == str(first_source.resolve())


def test_local_files_cli_fails_fast_for_same_name_different_directory_collision(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    first_source = tmp_path / "a" / "notes.txt"
    first_source.parent.mkdir(parents=True)
    first_source.write_text("First file.\n", encoding="utf-8")
    second_source = tmp_path / "b" / "notes.txt"
    second_source.parent.mkdir(parents=True)
    second_source.write_text("Second file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(first_source),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    first_artifact = output_dir / "pages" / "notes.md"
    original_artifact = first_artifact.read_text(encoding="utf-8")
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "local_files",
                "--file-path",
                str(second_source),
                "--output-dir",
                str(output_dir),
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "knowledge-adapters local_files: error:" in captured.err
    assert f"Artifact path collision: {first_artifact}" in captured.err
    assert f"source file {first_source.resolve()}" in captured.err
    assert f"this run resolves {second_source.resolve()}." in captured.err
    assert first_artifact.read_text(encoding="utf-8") == original_artifact
    manifest_payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["files"][0]["canonical_id"] == str(first_source.resolve())


def test_local_files_cli_prune_flag_reports_and_deletes_stale_manifest_file(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    first_source = tmp_path / "first.txt"
    first_source.write_text("First file.\n", encoding="utf-8")
    second_source = tmp_path / "second.txt"
    second_source.write_text("Second file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    assert (
        main(
            [
                "local_files",
                "--file-path",
                str(first_source),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    stale_output = output_dir / "pages" / "first.md"
    unmanifested_output = output_dir / "pages" / "unmanifested.md"
    unmanifested_output.write_text("keep\n", encoding="utf-8")

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(second_source),
            "--output-dir",
            str(output_dir),
            "--prune-stale-artifacts",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Summary: wrote 1, skipped 0" in captured.out
    assert "stale_artifacts: 1" in captured.out
    assert "pruned_stale_artifacts: 1" in captured.out
    assert str(stale_output) in captured.out
    assert not stale_output.exists()
    assert unmanifested_output.read_text(encoding="utf-8") == "keep\n"
    assert (output_dir / "pages" / "second.md").exists()


def test_local_files_cli_reports_orphaned_artifacts_without_deleting(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "current.txt"
    source_file.write_text("Current file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    orphaned_output = output_dir / "pages" / "orphaned.md"
    orphaned_output.parent.mkdir(parents=True)
    orphaned_output.write_text("orphaned\n", encoding="utf-8")
    ignored_non_markdown = output_dir / "pages" / "ignored.txt"
    ignored_non_markdown.write_text("ignored\n", encoding="utf-8")
    outside_pages = output_dir / "other" / "orphaned.md"
    outside_pages.parent.mkdir(parents=True)
    outside_pages.write_text("outside\n", encoding="utf-8")

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(source_file),
            "--output-dir",
            str(output_dir),
            "--report-orphaned-artifacts",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert_orphaned_artifacts(captured.out, count=1, artifact_paths=[orphaned_output])
    assert "pruned_orphaned_artifacts" not in captured.out
    assert orphaned_output.read_text(encoding="utf-8") == "orphaned\n"
    assert ignored_non_markdown.read_text(encoding="utf-8") == "ignored\n"
    assert outside_pages.read_text(encoding="utf-8") == "outside\n"


def test_local_files_cli_prunes_orphaned_artifacts_only_under_pages_markdown(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "current.txt"
    source_file.write_text("Current file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    orphaned_output = output_dir / "pages" / "orphaned.md"
    orphaned_output.parent.mkdir(parents=True)
    orphaned_output.write_text("orphaned\n", encoding="utf-8")
    ignored_non_markdown = output_dir / "pages" / "ignored.txt"
    ignored_non_markdown.write_text("ignored\n", encoding="utf-8")

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(source_file),
            "--output-dir",
            str(output_dir),
            "--prune-orphaned-artifacts",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "orphaned_artifacts: 1" in captured.out
    assert "pruned_orphaned_artifacts: 1" in captured.out
    assert "Pruned orphaned artifacts:" in captured.out
    assert str(orphaned_output) in captured.out
    assert not orphaned_output.exists()
    assert ignored_non_markdown.read_text(encoding="utf-8") == "ignored\n"
    assert (output_dir / "pages" / "current.md").exists()


def test_local_files_cli_prunes_stale_and_orphaned_artifacts_separately(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    first_source = tmp_path / "first.txt"
    first_source.write_text("First file.\n", encoding="utf-8")
    second_source = tmp_path / "second.txt"
    second_source.write_text("Second file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    assert (
        main(
            [
                "local_files",
                "--file-path",
                str(first_source),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    stale_output = output_dir / "pages" / "first.md"
    orphaned_output = output_dir / "pages" / "orphaned.md"
    orphaned_output.write_text("orphaned\n", encoding="utf-8")

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(second_source),
            "--output-dir",
            str(output_dir),
            "--prune-stale-artifacts",
            "--prune-orphaned-artifacts",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "stale_artifacts: 1" in captured.out
    assert "pruned_stale_artifacts: 1" in captured.out
    assert "orphaned_artifacts: 1" in captured.out
    assert "pruned_orphaned_artifacts: 1" in captured.out
    assert str(stale_output) in captured.out
    assert str(orphaned_output) in captured.out
    assert not stale_output.exists()
    assert not orphaned_output.exists()
    assert (output_dir / "pages" / "second.md").exists()


def test_local_files_cli_prune_dry_run_reports_candidates_without_deleting(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    first_source = tmp_path / "first.txt"
    first_source.write_text("First file.\n", encoding="utf-8")
    second_source = tmp_path / "second.txt"
    second_source.write_text("Second file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    assert (
        main(
            [
                "local_files",
                "--file-path",
                str(first_source),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    stale_output = output_dir / "pages" / "first.md"
    stale_contents = stale_output.read_text(encoding="utf-8")

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(second_source),
            "--output-dir",
            str(output_dir),
            "--dry-run",
            "--prune-stale-artifacts",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Summary: would write 1, would skip 0" in captured.out
    assert "stale_artifacts: 1" in captured.out
    assert "would_prune_stale_artifacts: 1" in captured.out
    assert str(stale_output) in captured.out
    assert stale_output.read_text(encoding="utf-8") == stale_contents


def test_local_files_cli_dry_run_prune_orphaned_reports_without_deleting(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "current.txt"
    source_file.write_text("Current file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    orphaned_output = output_dir / "pages" / "orphaned.md"
    orphaned_output.parent.mkdir(parents=True)
    orphaned_output.write_text("orphaned\n", encoding="utf-8")

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(source_file),
            "--output-dir",
            str(output_dir),
            "--dry-run",
            "--prune-orphaned-artifacts",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Summary: would write 1, would skip 0" in captured.out
    assert_orphaned_artifacts(captured.out, count=1, artifact_paths=[orphaned_output])
    assert "would_prune_orphaned_artifacts: 1" in captured.out
    assert orphaned_output.read_text(encoding="utf-8") == "orphaned\n"


def test_local_files_cli_prune_rejects_outside_manifest_path_before_delete(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "current.txt"
    source_file.write_text("Current file.\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    current_output = output_dir / "pages" / "current.md"
    safe_stale_output = output_dir / "pages" / "safe-stale.md"
    outside_output = tmp_path / "outside.md"
    safe_stale_output.parent.mkdir(parents=True)
    current_output.write_text("old current\n", encoding="utf-8")
    safe_stale_output.write_text("safe stale\n", encoding="utf-8")
    outside_output.write_text("outside\n", encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-20T00:00:00Z",
                "files": [
                    {
                        "canonical_id": str(source_file.resolve()),
                        "source_url": source_file.resolve().as_uri(),
                        "output_path": "pages/current.md",
                        "title": "current.txt",
                    },
                    {
                        "canonical_id": "safe-stale",
                        "source_url": "file:///safe-stale",
                        "output_path": "pages/safe-stale.md",
                        "title": "safe-stale",
                    },
                    {
                        "canonical_id": "outside",
                        "source_url": "file:///outside",
                        "output_path": str(outside_output),
                        "title": "outside",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "local_files",
                "--file-path",
                str(source_file),
                "--output-dir",
                str(output_dir),
                "--prune-stale-artifacts",
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "knowledge-adapters local_files: error:" in captured.err
    assert "outside output_dir" in captured.err
    assert current_output.read_text(encoding="utf-8") == "old current\n"
    assert safe_stale_output.read_text(encoding="utf-8") == "safe stale\n"
    assert outside_output.read_text(encoding="utf-8") == "outside\n"


def test_fetch_file_reports_permission_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "notes.txt"
    source_file.write_text("Hello from disk.\n", encoding="utf-8")

    def _raise_permission_error(self: Path, *, encoding: str) -> str:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "read_text", _raise_permission_error)

    with pytest.raises(
        ValueError,
        match=rf"File is not readable: {source_file.resolve()}\. Check the file permissions\.",
    ):
        fetch_file(str(source_file))


def test_local_files_cli_reports_missing_file_with_actionable_error(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    missing_file = tmp_path / "missing.txt"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "local_files",
                "--file-path",
                str(missing_file),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Local files adapter invoked" not in captured.out
    assert "knowledge-adapters local_files: error:" in captured.err
    assert f"File does not exist: {missing_file}." in captured.err
    assert "Verify --file-path and try again." in captured.err


def test_local_files_cli_reports_non_file_input_path(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_dir = tmp_path / "notes"
    source_dir.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "local_files",
                "--file-path",
                str(source_dir),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert f"Path is not a regular file: {source_dir}." in captured.err
    assert "local_files reads one UTF-8 text file at a time" in captured.err
    assert "directories are not supported." in captured.err


def test_local_files_cli_writes_empty_utf8_file_with_empty_content_section(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "empty.txt"
    source_file.write_text("", encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "local_files",
            "--file-path",
            str(source_file),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert (
        "content_status: empty UTF-8 file; output will contain metadata and an empty "
        "content section"
    ) in captured.out

    output_path = output_dir / "pages" / "empty.md"
    assert_markdown_document(
        output_path.read_text(encoding="utf-8"),
        title="empty.txt",
        metadata={
            "source": "local_files",
            "canonical_id": str(source_file.resolve()),
            "parent_id": "",
            "source_url": source_file.resolve().as_uri(),
            "fetched_at": "",
            "updated_at": "",
            "adapter": "local_files",
        },
        content="",
    )


def test_local_files_cli_reports_non_utf8_input_with_actionable_error(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "notes.txt"
    source_file.write_bytes(b"\xff\xfe\x00not-utf8")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "local_files",
                "--file-path",
                str(source_file),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert f"File is not valid UTF-8 text: {source_file.resolve()}." in captured.err
    assert "local_files reads one UTF-8 text file at a time" in captured.err
    assert "does not support binary or other encoded input." in captured.err
    assert "Re-save the file as UTF-8 text and try again." in captured.err


def test_local_files_cli_reports_invalid_output_dir(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "notes.txt"
    source_file.write_text("Hello from disk.\n", encoding="utf-8")
    output_path = tmp_path / "artifacts.txt"
    output_path.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "local_files",
                "--file-path",
                str(source_file),
                "--output-dir",
                str(output_path),
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert f"Output path is not a directory: {output_path}." in captured.err
    assert "Verify --output-dir and use a directory path." in captured.err
