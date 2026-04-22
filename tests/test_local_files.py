import json
from pathlib import Path

import pytest
from pytest import CaptureFixture

from knowledge_adapters.cli import main
from knowledge_adapters.local_files.client import fetch_file
from knowledge_adapters.local_files.normalize import normalize_to_markdown


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

    assert "- source: local_files\n" in markdown
    assert "- adapter: local_files\n" in markdown
    assert markdown.endswith("Hello from disk.\n")


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
    assert "Summary: wrote 1 file" in captured.out
    assert f"Artifact: {output_dir / 'pages' / 'meeting-notes.md'}" in captured.out
    assert f"Manifest: {output_dir / 'manifest.json'}" in captured.out

    output_path = output_dir / "pages" / "meeting-notes.md"
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == (
        f"""# meeting-notes.txt

## Metadata
- source: local_files
- canonical_id: {source_file.resolve()}
- parent_id:
- source_url: {source_file.resolve().as_uri()}
- fetched_at:
- updated_at:
- adapter: local_files

## Content

Line one.
Line two.
"""
    )

    payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert payload["files"] == [
        {
            "canonical_id": str(source_file.resolve()),
            "source_url": source_file.resolve().as_uri(),
            "output_path": "pages/meeting-notes.md",
            "title": "meeting-notes.txt",
        }
    ]
    assert isinstance(payload["generated_at"], str)


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
    assert f"artifact_path: {output_path}" in captured.out
    assert f"manifest_path: {output_dir / 'manifest.json'}" in captured.out
    assert "content_status: UTF-8 text with content" in captured.out
    assert "action: would write" in captured.out
    assert "Summary: would write 1, would skip 0" in captured.out
    assert "Dry run complete. No files written." in captured.out
    assert "Line one." in captured.out


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
    assert output_path.read_text(encoding="utf-8") == (
        f"""# empty.txt

## Metadata
- source: local_files
- canonical_id: {source_file.resolve()}
- parent_id:
- source_url: {source_file.resolve().as_uri()}
- fetched_at:
- updated_at:
- adapter: local_files

## Content


"""
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
