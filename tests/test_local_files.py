import json
from pathlib import Path

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


def test_local_files_cli_writes_normalized_markdown(tmp_path: Path) -> None:
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
    assert f"Dry run: would write {output_path}" in captured.out
    assert "Line one." in captured.out
