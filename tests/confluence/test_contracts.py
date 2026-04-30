from __future__ import annotations

from pathlib import Path

from pytest import CaptureFixture

from knowledge_adapters.cli import main
from tests.adapter_contracts import (
    assert_manifest_success_contract,
    assert_normalized_markdown_contract,
)


def test_confluence_stub_write_satisfies_adapter_success_contract(
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
        ]
    )

    assert exit_code == 0
    capsys.readouterr()

    source_url = "https://example.com/wiki/pages/viewpage.action?pageId=12345"
    artifact_path = output_dir / "pages" / "12345.md"
    assert_normalized_markdown_contract(
        artifact_path.read_text(encoding="utf-8"),
        source="confluence",
        adapter="confluence",
        canonical_id="12345",
        source_url=source_url,
        title="stub-page-12345",
        content="Stub content for page 12345.",
    )
    assert_manifest_success_contract(
        output_dir / "manifest.json",
        expected_files=[
            {
                "canonical_id": "12345",
                "source_url": source_url,
                "output_path": "pages/12345.md",
                "title": "stub-page-12345",
            }
        ],
    )
