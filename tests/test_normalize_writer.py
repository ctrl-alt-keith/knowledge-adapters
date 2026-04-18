from pathlib import Path

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
