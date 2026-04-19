from pathlib import Path

import pytest
from pytest import CaptureFixture

from knowledge_adapters.cli import main
from knowledge_adapters.confluence.normalize import normalize_to_markdown
from knowledge_adapters.confluence.writer import write_markdown


def test_normalize_to_markdown_includes_expected_sections_and_fields() -> None:
    page = {
        "title": "Team Notes",
        "canonical_id": "12345",
        "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
        "content": "Hello from Confluence.",
    }

    markdown = normalize_to_markdown(page)

    expected = """# Team Notes

## Metadata
- source: confluence
- canonical_id: 12345
- parent_id:
- source_url: https://example.com/wiki/spaces/ENG/pages/12345
- fetched_at:
- updated_at:
- adapter: confluence

## Content

Hello from Confluence.
"""

    assert markdown == expected


def test_normalize_to_markdown_uses_safe_defaults_for_missing_fields() -> None:
    markdown = normalize_to_markdown({})

    assert markdown.startswith("# untitled\n")
    assert "- canonical_id: \n" in markdown
    assert "- source_url: \n" in markdown
    assert markdown.endswith("\n\n")


def test_write_markdown_writes_to_pages_subdirectory(tmp_path: Path) -> None:
    markdown = "# Title\n"

    output_path = write_markdown(str(tmp_path), "page-42", markdown)

    assert output_path == tmp_path / "pages" / "page-42.md"
    assert output_path.read_text(encoding="utf-8") == markdown


def test_write_markdown_dry_run_returns_path_without_writing(tmp_path: Path) -> None:
    markdown = "# Title\n"

    output_path = write_markdown(str(tmp_path), "page-42", markdown, dry_run=True)

    assert output_path == tmp_path / "pages" / "page-42.md"
    assert not output_path.exists()


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

    captured = capsys.readouterr()
    assert f"Dry run: would write {output_path}" in captured.out
    assert "# stub-page-12345" in captured.out


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
        "'not-a-page'. Expected a Confluence page ID or full Confluence page URL.\n"
    ) in captured.err
