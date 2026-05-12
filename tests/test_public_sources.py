from __future__ import annotations

import json
from collections.abc import Mapping
from email.message import Message
from pathlib import Path
from typing import Any, Literal

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.public_pdf.client import PublicPdfDocument
from knowledge_adapters.public_pdf.normalize import (
    STABLE_FETCHED_AT_NOTE,
)
from knowledge_adapters.public_pdf.normalize import (
    normalize_extracted_pages as normalize_pdf_pages,
)
from knowledge_adapters.public_pdf.normalize import (
    normalize_extracted_pages_with_replay_metadata as normalize_pdf_pages_with_metadata,
)
from knowledge_adapters.public_pdf.normalize import (
    normalize_to_markdown as normalize_pdf,
)
from knowledge_adapters.public_pdf.writer import markdown_path as pdf_markdown_path
from knowledge_adapters.public_sources import (
    fetch_public_url,
    output_name_for_url,
    validate_public_http_url,
)
from knowledge_adapters.public_webpage.client import PublicWebpageDocument, fetch_webpage
from knowledge_adapters.public_webpage.normalize import normalize_to_markdown as normalize_webpage
from knowledge_adapters.public_webpage.writer import markdown_path as webpage_markdown_path
from tests.artifact_assertions import assert_manifest_entries, assert_markdown_document

MEANINGFULTECH_URL = "https://meaningfultech.com/p/the-vibe-coding-illusion-why-faster"
DORA_2023_PDF_URL = (
    "https://dora.dev/research/2023/dora-report/"
    "2023-dora-accelerate-state-of-devops-report.pdf"
)


class _FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        content: bytes,
        content_type: str,
        charset: str | None = None,
    ) -> None:
        self._url = url
        self._content = content
        self.headers = Message()
        self.headers["Content-Type"] = (
            f"{content_type}; charset={charset}" if charset is not None else content_type
        )
        self.headers["Content-Length"] = str(len(content))

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            return self._content
        return self._content[:amount]


def test_fetch_public_url_uses_in_memory_response_and_metadata(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: int) -> _FakeResponse:
        del timeout
        assert request.full_url == MEANINGFULTECH_URL
        return _FakeResponse(
            url=MEANINGFULTECH_URL,
            content=b"<html>Hello</html>",
            content_type="text/html",
            charset="utf-8",
        )

    monkeypatch.setattr("knowledge_adapters.public_sources.urlopen", fake_urlopen)

    fetched = fetch_public_url(
        MEANINGFULTECH_URL,
        accepted_content_types=("text/html",),
        max_bytes=1000,
    )

    assert fetched.url == MEANINGFULTECH_URL
    assert fetched.final_url == MEANINGFULTECH_URL
    assert fetched.content == b"<html>Hello</html>"
    assert fetched.content_type == "text/html"
    assert fetched.content_charset == "utf-8"
    assert fetched.retrieved_at.endswith("Z")


@pytest.mark.parametrize(
    "url",
    (
        "https://example.com/article",
        "http://subdomain.example.org/report",
        "https://8.8.8.8/dns-over-https",
        "https://[2606:4700:4700::1111]/",
    ),
)
def test_validate_public_http_url_accepts_public_http_targets(url: str) -> None:
    validate_public_http_url(url)


@pytest.mark.parametrize(
    "url",
    (
        "ftp://example.com/report",
        "file:///etc/passwd",
        "https://user:pass@example.com/report",
        "https://localhost/report",
        "https://localhost./report",
        "https://printer.local/report",
        "https://printer.local./report",
        "https://127.0.0.1/report",
        "https://[::1]/report",
        "https://10.0.0.1/report",
        "https://172.16.0.1/report",
        "https://192.168.0.1/report",
        "https://169.254.1.1/report",
        "https://169.254.169.254/latest/meta-data/",
        "https://[fe80::1]/report",
        "https://224.0.0.1/report",
        "https://[ff02::1]/report",
        "https://0.0.0.0/report",
        "https://[::]/report",
        "https://240.0.0.1/report",
        "https://[2001:db8::1]/report",
    ),
)
def test_validate_public_http_url_rejects_local_private_internal_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_http_url(url)


def test_fetch_public_url_does_not_request_rejected_original_url(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        del request, timeout
        raise AssertionError("blocked original URL should not be requested")

    monkeypatch.setattr("knowledge_adapters.public_sources.urlopen", fake_urlopen)

    with pytest.raises(ValueError, match="private IP"):
        fetch_public_url(
            "https://10.0.0.1/report",
            accepted_content_types=("text/html",),
            max_bytes=1000,
        )


def test_fetch_public_url_revalidates_and_rejects_redirect_final_url(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        del request, timeout
        return _FakeResponse(
            url="https://169.254.169.254/latest/meta-data/",
            content=b"metadata",
            content_type="text/html",
            charset="utf-8",
        )

    monkeypatch.setattr("knowledge_adapters.public_sources.urlopen", fake_urlopen)

    with pytest.raises(ValueError, match="link-local"):
        fetch_public_url(
            "https://example.com/redirect",
            accepted_content_types=("text/html",),
            max_bytes=1000,
        )


def test_fetch_webpage_extracts_title_and_visible_text(monkeypatch: MonkeyPatch) -> None:
    html = b"""
<html>
  <head><title>The Vibe Coding Illusion</title><style>hidden</style></head>
  <body>
    <article>
      <h1>The Vibe Coding Illusion</h1>
      <p>Faster typing is not the same as faster delivery.</p>
      <script>doNotKeep()</script>
      <p>Review still matters.</p>
    </article>
  </body>
</html>
"""

    def fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        del request, timeout
        return _FakeResponse(
            url=MEANINGFULTECH_URL,
            content=html,
            content_type="text/html",
            charset="utf-8",
        )

    monkeypatch.setattr("knowledge_adapters.public_sources.urlopen", fake_urlopen)

    document = fetch_webpage(MEANINGFULTECH_URL)

    assert document.title == "The Vibe Coding Illusion"
    assert document.source_url == MEANINGFULTECH_URL
    assert "Faster typing is not the same as faster delivery." in document.content
    assert "Review still matters." in document.content
    assert "doNotKeep" not in document.content
    assert "Unreviewed candidate material" in document.extraction_notes


def test_public_webpage_normalizer_marks_candidate_status() -> None:
    markdown = normalize_webpage(
        {
            "title": "The Vibe Coding Illusion",
            "canonical_id": MEANINGFULTECH_URL,
            "source_url": MEANINGFULTECH_URL,
            "fetched_at": "2026-05-11T12:00:00Z",
            "content": "Article text.",
            "extraction_notes": "Unreviewed candidate material. HTML extraction note.",
        }
    )

    assert_markdown_document(
        markdown,
        title="The Vibe Coding Illusion",
        metadata={
            "source": "public_webpage",
            "canonical_id": MEANINGFULTECH_URL,
            "parent_id": "",
            "source_url": MEANINGFULTECH_URL,
            "fetched_at": "2026-05-11T12:00:00Z",
            "updated_at": "",
            "adapter": "public_webpage",
            "candidate_status": "unreviewed",
            "extraction_notes": "Unreviewed candidate material. HTML extraction note.",
        },
        content=(
            "> This is unreviewed candidate material generated from an external public source.\n\n"
            "Article text."
        ),
    )


def test_public_pdf_normalizer_marks_limitations() -> None:
    markdown = normalize_pdf(
        {
            "title": "DORA 2023 Accelerate State of DevOps Report",
            "canonical_id": DORA_2023_PDF_URL,
            "source_url": DORA_2023_PDF_URL,
            "fetched_at": "2026-05-11T12:00:00Z",
            "page_count": 2,
            "content": "## Page 1\n\nReport text.",
            "extraction_notes": "Unreviewed candidate material. PDF extraction limitations.",
        }
    )

    assert_markdown_document(
        markdown,
        title="DORA 2023 Accelerate State of DevOps Report",
        metadata={
            "source": "public_pdf",
            "canonical_id": DORA_2023_PDF_URL,
            "parent_id": "",
            "source_url": DORA_2023_PDF_URL,
            "fetched_at": STABLE_FETCHED_AT_NOTE,
            "updated_at": "",
            "adapter": "public_pdf",
            "candidate_status": "unreviewed",
            "page_count": "2",
            "extraction_notes": "Unreviewed candidate material. PDF extraction limitations.",
        },
        content=(
            "> This is unreviewed candidate material generated from an external public "
            "PDF/report.\n\n## Page 1\n\nReport text."
        ),
    )


def test_public_pdf_page_normalization_repairs_broken_url_spacing() -> None:
    normalized_pages = normalize_pdf_pages(
        [
            (
                "Read the report at https:/ /dora.dev/research/2023/dora-report/ "
                "or mirror https: //example.com/report.pdf."
            )
        ]
    )

    assert normalized_pages == [
        (
            "Read the report at https://dora.dev/research/2023/dora-report/ "
            "or mirror https://example.com/report.pdf."
        )
    ]


def test_public_pdf_page_normalization_repairs_url_path_line_wrap() -> None:
    normalized_pages = normalize_pdf_pages(
        [
            (
                "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-\n"
                "assisted-software-development"
            )
        ]
    )

    assert normalized_pages == [
        (
            "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-"
            "assisted-software-development"
        )
    ]


def test_public_pdf_page_normalization_keeps_normal_hyphenated_prose() -> None:
    normalized_pages = normalize_pdf_pages(
        [
            (
                "The review describes AI-assisted-\n"
                "software delivery without a URL on the prior line."
            )
        ]
    )

    assert normalized_pages == [
        (
            "The review describes AI-assisted-\n"
            "software delivery without a URL on the prior line."
        )
    ]


def test_public_pdf_page_normalization_keeps_url_path_split_across_blank_line() -> None:
    normalized_pages = normalize_pdf_pages(
        [
            (
                "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-\n"
                "\n"
                "assisted-software-development"
            )
        ]
    )

    assert normalized_pages == [
        (
            "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-\n\n"
            "assisted-software-development"
        )
    ]


def test_public_pdf_page_normalization_keeps_url_path_split_across_pages() -> None:
    normalized_pages = normalize_pdf_pages(
        [
            "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-",
            "assisted-software-development",
        ]
    )

    assert normalized_pages == [
        "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-",
        "assisted-software-development",
    ]


def test_public_pdf_page_normalization_suppresses_repeated_footer_lines() -> None:
    normalized_pages = normalize_pdf_pages(
        [
            "Executive summary\n2023 Accelerate State of DevOps Report\n1",
            "Key findings\n2023 Accelerate State of DevOps Report\n2",
            "Closing notes\n2023 Accelerate State of DevOps Report\n3",
        ]
    )

    assert normalized_pages == [
        "Executive summary",
        "Key findings",
        "Closing notes",
    ]


def test_public_pdf_page_normalization_reports_replay_quality_metadata() -> None:
    raw_pages = [
        (
            "Metric   Value\n"
            "Read https:/ /example.com/report\n"
            "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-\n"
            "assisted-software-development\n"
            "DORA Report\n"
            "1"
        ),
        "Findings\nDORA Report\n2",
    ]

    first_pages, first_metadata = normalize_pdf_pages_with_metadata(raw_pages)
    second_pages, second_metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert first_pages == [
        (
            "Metric   Value\n"
            "Read https://example.com/report\n"
            "Source: https://cloud.google.com/resources/content/dora-roi-of-ai-"
            "assisted-software-development"
        ),
        "Findings",
    ]
    assert first_pages == second_pages
    assert first_metadata == second_metadata
    assert first_metadata["url_spacing_normalization"] == {
        "activity": "normalized",
        "replacement_count": 1,
        "affected_page_count": 1,
    }
    assert first_metadata["url_path_line_wrap_normalization"] == {
        "activity": "normalized",
        "repair_count": 1,
        "affected_page_count": 1,
    }
    assert first_metadata["repeated_footer_suppression"] == {
        "activity": "suppressed",
        "basis": "anchored_trailing_footer_blocks",
        "suppressed_line_count": 4,
        "affected_page_count": 2,
        "detected_footer_pattern_count": 1,
        "detected_anchored_footer_block_count": 1,
        "suppressed_anchored_footer_block_count": 1,
        "skipped_anchored_footer_block_count": 0,
        "suppressed_numeric_page_line_count": 2,
        "skipped_numeric_risk_count": 0,
        "detected_anchored_footer_blocks": [
            {
                "anchor_signature": "dora report",
                "anchor_depth": 2,
                "numeric_depth": 1,
                "page_count": 2,
                "numeric_values": [1, 2],
            }
        ],
        "skipped_numeric_risk_cases": [],
    }
    assert first_metadata["page_count_context"] == {
        "page_count": 2,
        "pages_with_extracted_text_count": 2,
        "empty_page_count": 0,
    }
    assert first_metadata["possible_layout_artifact_density"] == {
        "basis": "normalized_extracted_text_lines",
        "line_count": 4,
        "possible_artifact_line_count": 1,
        "possible_artifact_line_ratio": "0.250",
    }

    markdown = normalize_pdf(
        {
            "title": "Report",
            "canonical_id": DORA_2023_PDF_URL,
            "source_url": DORA_2023_PDF_URL,
            "page_count": 2,
            "content": "## Page 1\n\nMetric   Value",
            "replay_quality_metadata": first_metadata,
        }
    )

    assert "- candidate_status: unreviewed" in markdown
    assert (
        "- replay_quality_metadata_note: informational only; does not authorize retention "
        "or promotion"
    ) in markdown
    assert "- replay_quality_url_spacing_normalization_count: 1" in markdown
    assert "- replay_quality_url_path_line_wrap_repair_count: 1" in markdown
    assert "- replay_quality_repeated_footer_suppressed_line_count: 4" in markdown
    assert (
        "- replay_quality_repeated_footer_detected_anchored_block_count: 1"
        in markdown
    )
    assert (
        "- replay_quality_repeated_footer_suppressed_numeric_page_line_count: 2"
        in markdown
    )
    assert "- replay_quality_repeated_footer_skipped_numeric_risk_count: 0" in markdown
    assert "- replay_quality_possible_layout_artifact_lines: 1/4 (0.250)" in markdown


def test_public_pdf_footer_page_number_diagnostics_measure_safe_repeated_blocks() -> None:
    raw_pages = [
        "Executive summary\nDORA Report\n1",
        "Key findings\nDORA Report\n2",
        "Closing notes\nDORA Report\n3",
    ]

    normalized_pages, metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert normalized_pages == [
        "Executive summary",
        "Key findings",
        "Closing notes",
    ]
    footer_page_noise = _metadata_mapping(
        metadata, "footer_page_number_noise_diagnostics"
    )
    assert footer_page_noise == {
        "activity": "measured",
        "basis": "post_url_normalization_pre_footer_suppression_extracted_pages",
        "candidate_window": {
            "trailing_nonempty_line_count": 3,
            "min_repeated_pages": 2,
        },
        "repeated_trailing_footer_block_count": 2,
        "repeated_trailing_footer_signature_count": 2,
        "bare_numeric_line_count": 3,
        "bare_numeric_trailing_line_count": 3,
        "repeated_bare_numeric_trailing_signature_count": 1,
        "bare_numeric_adjacent_to_numeric_content_count": 0,
        "mid_page_footer_like_line_count": 0,
        "risk_note": (
            "bare numeric lines may be page numbers or meaningful table, calculator, "
            "or report values; diagnostics do not authorize suppression"
        ),
    }
    repeated_footer = _metadata_mapping(metadata, "repeated_footer_suppression")
    assert repeated_footer["detected_anchored_footer_block_count"] == 1
    assert repeated_footer["suppressed_numeric_page_line_count"] == 3
    assert repeated_footer["skipped_numeric_risk_count"] == 0


def test_public_pdf_page_normalization_keeps_bare_numeric_calculator_rows() -> None:
    raw_pages = [
        "Calculator\nInput value 10\n15\nOutput value 25",
        "Calculator\nInput value 12\n18\nOutput value 30",
    ]

    normalized_pages, metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert normalized_pages == raw_pages
    repeated_footer = _metadata_mapping(metadata, "repeated_footer_suppression")
    assert repeated_footer["suppressed_numeric_page_line_count"] == 0
    assert repeated_footer["skipped_numeric_risk_count"] == 0


def test_public_pdf_page_normalization_keeps_bare_numeric_signatures_without_anchor() -> None:
    raw_pages = [
        "Executive summary\nImportant row\n1",
        "Key findings\nDifferent row\n2",
        "Closing notes\nAnother row\n3",
    ]

    normalized_pages, metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert normalized_pages == raw_pages
    footer_page_noise = _metadata_mapping(
        metadata, "footer_page_number_noise_diagnostics"
    )
    repeated_footer = _metadata_mapping(metadata, "repeated_footer_suppression")
    assert footer_page_noise["repeated_bare_numeric_trailing_signature_count"] == 1
    assert repeated_footer["suppressed_numeric_page_line_count"] == 0
    assert repeated_footer["detected_anchored_footer_block_count"] == 0


def test_public_pdf_footer_page_number_diagnostics_measure_numeric_content_risk() -> None:
    raw_pages = [
        "Calculator\nInput value 10\n15\nOutput value 25\nNotes A\nCheck A\nKeep A",
        "Calculator\nInput value 12\n18\nOutput value 30\nNotes B\nCheck B\nKeep B",
    ]

    normalized_pages, metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert normalized_pages == raw_pages
    footer_page_noise = _metadata_mapping(
        metadata, "footer_page_number_noise_diagnostics"
    )
    assert footer_page_noise["bare_numeric_line_count"] == 2
    assert footer_page_noise["bare_numeric_trailing_line_count"] == 0
    assert footer_page_noise["bare_numeric_adjacent_to_numeric_content_count"] == 2
    assert footer_page_noise["repeated_bare_numeric_trailing_signature_count"] == 0


def test_public_pdf_footer_page_number_diagnostics_measure_mid_page_footer_like_text() -> None:
    raw_pages = [
        "Intro\nDORA Report | 1\nBody\nMetric 5\nDetail A\nClosing A",
        "Intro\nDORA Report | 2\nBody\nMetric 6\nDetail B\nClosing B",
    ]

    normalized_pages, metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert normalized_pages == raw_pages
    footer_page_noise = _metadata_mapping(
        metadata, "footer_page_number_noise_diagnostics"
    )
    assert footer_page_noise["mid_page_footer_like_line_count"] == 2
    assert footer_page_noise["repeated_trailing_footer_block_count"] == 0
    assert footer_page_noise["bare_numeric_line_count"] == 0


def test_public_pdf_footer_page_number_diagnostics_measure_page_numbers_near_values() -> None:
    raw_pages = [
        "Table\nMetric value 12\n1\nTotal value 13\nNotes A\nCheck A\nEnd A",
        "Table\nMetric value 20\n2\nTotal value 22\nNotes B\nCheck B\nEnd B",
    ]

    normalized_pages, metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert normalized_pages == raw_pages
    footer_page_noise = _metadata_mapping(
        metadata, "footer_page_number_noise_diagnostics"
    )
    assert footer_page_noise["bare_numeric_line_count"] == 2
    assert footer_page_noise["bare_numeric_trailing_line_count"] == 0
    assert footer_page_noise["bare_numeric_adjacent_to_numeric_content_count"] == 2
    assert footer_page_noise["mid_page_footer_like_line_count"] == 0


def test_public_pdf_page_normalization_skips_anchored_numeric_lines_near_values() -> None:
    raw_pages = [
        "Findings\nMetric value 12\nDORA Report\n1",
        "Findings\nMetric value 20\nDORA Report\n2",
        "Findings\nMetric value 30\nDORA Report\n3",
    ]

    normalized_pages, metadata = normalize_pdf_pages_with_metadata(raw_pages)

    assert normalized_pages == raw_pages
    repeated_footer = _metadata_mapping(metadata, "repeated_footer_suppression")
    assert repeated_footer["activity"] == "none"
    assert repeated_footer["detected_anchored_footer_block_count"] == 1
    assert repeated_footer["suppressed_anchored_footer_block_count"] == 0
    assert repeated_footer["skipped_anchored_footer_block_count"] == 1
    assert repeated_footer["suppressed_numeric_page_line_count"] == 0
    assert repeated_footer["skipped_numeric_risk_count"] == 3
    assert repeated_footer["skipped_numeric_risk_cases"] == [
        {
            "anchor_signature": "dora report",
            "anchor_depth": 2,
            "numeric_depth": 1,
            "page_count": 3,
            "risk_page_count": 3,
            "reason": "meaningful_numeric_context_near_footer_candidate",
        }
    ]


def test_public_pdf_page_normalization_keeps_non_repeated_trailing_text() -> None:
    normalized_pages = normalize_pdf_pages(
        [
            "Executive summary\nImportant benchmark: 12",
            "Key findings\nDifferent closing detail: 13",
            "Closing notes\n2023 Accelerate State of DevOps Report | 3",
        ]
    )

    assert normalized_pages == [
        "Executive summary\nImportant benchmark: 12",
        "Key findings\nDifferent closing detail: 13",
        "Closing notes\n2023 Accelerate State of DevOps Report | 3",
    ]


def test_public_pdf_cli_keeps_candidate_content_stable_across_fetch_times(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    replay_quality_metadata = _sample_replay_quality_metadata()
    documents = iter(
        (
            PublicPdfDocument(
                title="DORA 2023 Accelerate State of DevOps Report",
                canonical_id=DORA_2023_PDF_URL,
                source_url=DORA_2023_PDF_URL,
                fetched_at="2026-05-11T12:00:00Z",
                content="## Page 1\n\nStable report candidate text.\n\n## Page 2\n\nMore text.",
                page_count=2,
                replay_quality_metadata=replay_quality_metadata,
            ),
            PublicPdfDocument(
                title="DORA 2023 Accelerate State of DevOps Report",
                canonical_id=DORA_2023_PDF_URL,
                source_url=DORA_2023_PDF_URL,
                fetched_at="2026-05-11T12:30:00Z",
                content="## Page 1\n\nStable report candidate text.\n\n## Page 2\n\nMore text.",
                page_count=2,
                replay_quality_metadata=replay_quality_metadata,
            ),
        )
    )

    def fake_fetch(url: str) -> PublicPdfDocument:
        assert url == DORA_2023_PDF_URL
        return next(documents)

    monkeypatch.setattr("knowledge_adapters.public_pdf.client.fetch_pdf", fake_fetch)

    assert (
        main(
            [
                "public_pdf",
                "--url",
                DORA_2023_PDF_URL,
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    output_path = pdf_markdown_path(str(output_dir), DORA_2023_PDF_URL)
    first_markdown = output_path.read_text(encoding="utf-8")
    first_manifest = _manifest_payload(output_dir / "manifest.json")

    assert (
        main(
            [
                "public_pdf",
                "--url",
                DORA_2023_PDF_URL,
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    second_markdown = output_path.read_text(encoding="utf-8")
    second_manifest = _manifest_payload(output_dir / "manifest.json")

    assert first_markdown == second_markdown
    assert STABLE_FETCHED_AT_NOTE in first_markdown
    assert "replay_quality_metadata_note: informational only" in first_markdown
    assert "replay_quality_url_spacing_normalization_count: 1" in first_markdown
    assert "replay_quality_repeated_footer_suppressed_line_count: 2" in first_markdown
    assert "2026-05-11T12:00:00Z" not in first_markdown
    assert "2026-05-11T12:30:00Z" not in second_markdown
    assert first_manifest["files"][0]["content_hash"] == second_manifest["files"][0]["content_hash"]
    assert first_manifest["files"][0]["fetched_at"] == "2026-05-11T12:00:00Z"
    assert second_manifest["files"][0]["fetched_at"] == "2026-05-11T12:30:00Z"
    assert (
        first_manifest["files"][0]["replay_quality_metadata"]
        == second_manifest["files"][0]["replay_quality_metadata"]
        == replay_quality_metadata
    )


def test_public_pdf_cli_changes_candidate_hash_when_extracted_content_changes(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"
    documents = iter(
        (
            PublicPdfDocument(
                title="DORA 2023 Accelerate State of DevOps Report",
                canonical_id=DORA_2023_PDF_URL,
                source_url=DORA_2023_PDF_URL,
                fetched_at="2026-05-11T12:00:00Z",
                content="## Page 1\n\nOriginal report candidate text.",
                page_count=1,
            ),
            PublicPdfDocument(
                title="DORA 2023 Accelerate State of DevOps Report",
                canonical_id=DORA_2023_PDF_URL,
                source_url=DORA_2023_PDF_URL,
                fetched_at="2026-05-11T12:30:00Z",
                content="## Page 1\n\nUpdated report candidate text.",
                page_count=1,
            ),
        )
    )

    def fake_fetch(url: str) -> PublicPdfDocument:
        assert url == DORA_2023_PDF_URL
        return next(documents)

    monkeypatch.setattr("knowledge_adapters.public_pdf.client.fetch_pdf", fake_fetch)

    assert (
        main(
            [
                "public_pdf",
                "--url",
                DORA_2023_PDF_URL,
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    output_path = pdf_markdown_path(str(output_dir), DORA_2023_PDF_URL)
    first_markdown = output_path.read_text(encoding="utf-8")
    first_manifest = _manifest_payload(output_dir / "manifest.json")

    assert (
        main(
            [
                "public_pdf",
                "--url",
                DORA_2023_PDF_URL,
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    second_markdown = output_path.read_text(encoding="utf-8")
    second_manifest = _manifest_payload(output_dir / "manifest.json")

    assert first_markdown != second_markdown
    assert "Original report candidate text." in first_markdown
    assert "Updated report candidate text." in second_markdown
    assert first_manifest["files"][0]["content_hash"] != second_manifest["files"][0]["content_hash"]


def test_public_webpage_cli_writes_candidate_markdown(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"

    def fake_fetch(url: str) -> PublicWebpageDocument:
        assert url == MEANINGFULTECH_URL
        return PublicWebpageDocument(
            title="The Vibe Coding Illusion",
            canonical_id=MEANINGFULTECH_URL,
            source_url=MEANINGFULTECH_URL,
            fetched_at="2026-05-11T12:00:00Z",
            content="Article candidate text.",
        )

    monkeypatch.setattr("knowledge_adapters.public_webpage.client.fetch_webpage", fake_fetch)

    exit_code = main(
        [
            "public_webpage",
            "--url",
            MEANINGFULTECH_URL,
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Public webpage adapter invoked" in captured.out
    assert "candidate_status: unreviewed" in captured.out
    assert "Summary: wrote 1, skipped 0" in captured.out

    output_path = webpage_markdown_path(str(output_dir), MEANINGFULTECH_URL)
    assert output_path.exists()
    assert "Article candidate text." in output_path.read_text(encoding="utf-8")
    assert_manifest_entries(
        output_dir / "manifest.json",
        files=[
            {
                "canonical_id": MEANINGFULTECH_URL,
                "source_url": MEANINGFULTECH_URL,
                "output_path": output_path.relative_to(output_dir).as_posix(),
                "title": "The Vibe Coding Illusion",
                "content_hash": _content_hash_from_manifest(output_dir / "manifest.json"),
            }
        ],
    )


def test_public_pdf_cli_dry_run_reports_limitations_without_writing(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "out"

    def fake_fetch(url: str) -> PublicPdfDocument:
        assert url == DORA_2023_PDF_URL
        return PublicPdfDocument(
            title="DORA 2023 Accelerate State of DevOps Report",
            canonical_id=DORA_2023_PDF_URL,
            source_url=DORA_2023_PDF_URL,
            fetched_at="2026-05-11T12:00:00Z",
            content="## Page 1\n\nReport candidate text.",
            page_count=1,
        )

    monkeypatch.setattr("knowledge_adapters.public_pdf.client.fetch_pdf", fake_fetch)

    exit_code = main(
        [
            "public_pdf",
            "--url",
            DORA_2023_PDF_URL,
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    output_path = pdf_markdown_path(str(output_dir), DORA_2023_PDF_URL)
    assert not output_path.exists()
    assert not (output_dir / "manifest.json").exists()

    captured = capsys.readouterr()
    assert "Public PDF/report adapter invoked" in captured.out
    assert "run_mode: dry-run" in captured.out
    assert "page_count: 1" in captured.out
    assert "candidate_status: unreviewed" in captured.out
    assert "PDF layout, tables, figures" in captured.out
    assert "Summary: would write 1, would skip 0" in captured.out
    assert "Report candidate text." in captured.out


def test_output_name_for_url_includes_slug_and_hash() -> None:
    output_name = output_name_for_url(DORA_2023_PDF_URL)

    assert output_name.startswith("2023-dora-accelerate-state-of-devops-report-")
    assert len(output_name.rsplit("-", maxsplit=1)[-1]) == 12


def _content_hash_from_manifest(manifest_path: Path) -> str:
    payload = _manifest_payload(manifest_path)
    files = payload["files"]
    assert isinstance(files, list)
    content_hash = files[0]["content_hash"]
    assert isinstance(content_hash, str)
    return content_hash


def _manifest_payload(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _metadata_mapping(
    metadata: Mapping[str, object], key: str
) -> Mapping[str, object]:
    value = metadata[key]
    assert isinstance(value, Mapping)
    return value


def _sample_replay_quality_metadata() -> dict[str, object]:
    return {
        "metadata_scope": "public_pdf_replay_quality",
        "metadata_note": "informational only; does not authorize retention or promotion",
        "page_count_context": {
            "page_count": 2,
            "pages_with_extracted_text_count": 2,
            "empty_page_count": 0,
        },
        "url_spacing_normalization": {
            "activity": "normalized",
            "replacement_count": 1,
            "affected_page_count": 1,
        },
        "url_path_line_wrap_normalization": {
            "activity": "none",
            "repair_count": 0,
            "affected_page_count": 0,
        },
        "repeated_footer_suppression": {
            "activity": "suppressed",
            "basis": "anchored_trailing_footer_blocks",
            "suppressed_line_count": 2,
            "affected_page_count": 2,
            "detected_footer_pattern_count": 1,
            "detected_anchored_footer_block_count": 1,
            "suppressed_anchored_footer_block_count": 1,
            "skipped_anchored_footer_block_count": 0,
            "suppressed_numeric_page_line_count": 1,
            "skipped_numeric_risk_count": 0,
            "detected_anchored_footer_blocks": [
                {
                    "anchor_signature": "sample report",
                    "anchor_depth": 2,
                    "numeric_depth": 1,
                    "page_count": 1,
                    "numeric_values": [1],
                }
            ],
            "skipped_numeric_risk_cases": [],
        },
        "possible_layout_artifact_density": {
            "basis": "normalized_extracted_text_lines",
            "line_count": 3,
            "possible_artifact_line_count": 1,
            "possible_artifact_line_ratio": "0.333",
        },
        "extraction_warnings": [
            "pdf_layout_tables_figures_footnotes_headers_reading_order_may_be_incomplete",
            "scanned_image_only_pages_may_be_missing",
        ],
    }
