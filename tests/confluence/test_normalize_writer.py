from pathlib import Path

from knowledge_adapters.confluence.normalize import normalize_to_markdown
from knowledge_adapters.confluence.writer import write_markdown
from knowledge_adapters.manifest import build_manifest_entry, write_manifest
from tests.artifact_assertions import (
    assert_manifest_entries,
    assert_manifest_entry,
    assert_markdown_document,
    manifest_file,
)


def test_normalize_to_markdown_includes_expected_sections_and_fields() -> None:
    page = {
        "title": "Team Notes",
        "canonical_id": "12345",
        "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
        "content": "Hello from Confluence.",
    }

    markdown = normalize_to_markdown(page)

    assert_markdown_document(
        markdown,
        title="Team Notes",
        metadata={
            "source": "confluence",
            "canonical_id": "12345",
            "parent_id": "",
            "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
            "fetched_at": "",
            "updated_at": "",
            "adapter": "confluence",
        },
        content="Hello from Confluence.",
    )


def test_normalize_to_markdown_uses_safe_defaults_for_missing_fields() -> None:
    markdown = normalize_to_markdown({})

    assert_markdown_document(
        markdown,
        title="untitled",
        metadata={
            "source": "confluence",
            "canonical_id": "",
            "parent_id": "",
            "source_url": "",
            "fetched_at": "",
            "updated_at": "",
            "adapter": "confluence",
        },
        content="",
    )


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


def test_build_manifest_entry_uses_relative_output_path_and_optional_title(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "pages" / "page-42.md"

    entry = build_manifest_entry(
        canonical_id="page-42",
        source_url="https://example.com/wiki/pages/42",
        output_path=output_path,
        output_dir=str(tmp_path),
        title="Page 42",
    )

    assert_manifest_entry(
        entry,
        canonical_id="page-42",
        source_url="https://example.com/wiki/pages/42",
        output_path="pages/page-42.md",
        title="Page 42",
    )


def test_write_manifest_writes_minimal_payload_for_current_run(tmp_path: Path) -> None:
    manifest = write_manifest(
        str(tmp_path),
        [
            {
                "canonical_id": "page-42",
                "source_url": "https://example.com/wiki/pages/42",
                "output_path": "pages/page-42.md",
            }
        ],
    )

    assert manifest == tmp_path / "manifest.json"

    assert_manifest_entries(
        manifest,
        files=[
            manifest_file(
                canonical_id="page-42",
                source_url="https://example.com/wiki/pages/42",
                output_path="pages/page-42.md",
            )
        ],
    )
