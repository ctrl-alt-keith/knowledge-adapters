from __future__ import annotations

from email.message import Message
from pathlib import Path
from typing import Any, Literal

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.public_pdf.client import PublicPdfDocument
from knowledge_adapters.public_pdf.normalize import normalize_to_markdown as normalize_pdf
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
            "fetched_at": "2026-05-11T12:00:00Z",
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
    import json

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload["files"]
    assert isinstance(files, list)
    content_hash = files[0]["content_hash"]
    assert isinstance(content_hash, str)
    return content_hash
