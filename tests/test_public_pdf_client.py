from __future__ import annotations

from typing import Any

import pytest
from pytest import MonkeyPatch

from knowledge_adapters.public_pdf import client
from knowledge_adapters.public_sources import FetchedPublicResource


class _FakePdfPage:
    def __init__(self, text: str | Exception) -> None:
        self._text = text

    def extract_text(self) -> str:
        if isinstance(self._text, Exception):
            raise self._text
        return self._text


class _FakePdfReader:
    def __init__(self, _: Any, *, pages: list[_FakePdfPage], title: str | None) -> None:
        self.pages = pages
        self.metadata = type("Metadata", (), {"title": title})()


def _fetched_pdf() -> FetchedPublicResource:
    return FetchedPublicResource(
        url="https://example.com/reports/report.pdf",
        final_url="https://cdn.example.com/releases/report.pdf",
        content=b"synthetic pdf bytes",
        content_type="application/pdf",
        content_charset=None,
        retrieved_at="2026-08-25T12:00:00Z",
    )


def test_fetch_pdf_assembles_normalized_document(monkeypatch: MonkeyPatch) -> None:
    observed_fetch: dict[str, object] = {}

    def fake_fetch_public_url(url: str, **kwargs: object) -> FetchedPublicResource:
        observed_fetch["url"] = url
        observed_fetch.update(kwargs)
        return _fetched_pdf()

    class FakeReader(_FakePdfReader):
        def __init__(self, stream: Any) -> None:
            assert stream.read() == b"synthetic pdf bytes"
            super().__init__(
                stream,
                pages=[_FakePdfPage("First"), _FakePdfPage("Second")],
                title=" Report ",
            )

    monkeypatch.setattr(client, "fetch_public_url", fake_fetch_public_url)
    monkeypatch.setattr(client, "PdfReader", FakeReader)
    monkeypatch.setattr(
        client,
        "normalize_extracted_pages_with_replay_metadata",
        lambda pages: ([f"normalized {page}" for page in pages], {"normalized": True}),
    )

    document = client.fetch_pdf("https://example.com/reports/report.pdf")

    assert observed_fetch == {
        "url": "https://example.com/reports/report.pdf",
        "accepted_content_types": ("application/pdf",),
        "max_bytes": client.MAX_PDF_BYTES,
    }
    assert document.title == "Report"
    assert document.canonical_id == "https://cdn.example.com/releases/report.pdf"
    assert document.fetched_at == "2026-08-25T12:00:00Z"
    assert document.content == "## Page 1\n\nnormalized First\n\n## Page 2\n\nnormalized Second"
    assert document.page_count == 2
    assert document.replay_quality_metadata == {"normalized": True}


def test_fetch_pdf_reports_unparseable_bytes(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(client, "fetch_public_url", lambda *args, **kwargs: _fetched_pdf())

    def raise_parse_error(stream: Any) -> None:
        del stream
        raise RuntimeError("bad pdf")

    monkeypatch.setattr(client, "PdfReader", raise_parse_error)

    with pytest.raises(ValueError, match="Could not parse PDF bytes"):
        client.fetch_pdf("https://example.com/reports/report.pdf")


def test_fetch_pdf_reports_page_extraction_failure(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(client, "fetch_public_url", lambda *args, **kwargs: _fetched_pdf())

    class FakeReader(_FakePdfReader):
        def __init__(self, stream: Any) -> None:
            del stream
            super().__init__(
                None,
                pages=[_FakePdfPage("First"), _FakePdfPage(RuntimeError("bad page"))],
                title=None,
            )

    monkeypatch.setattr(client, "PdfReader", FakeReader)

    with pytest.raises(ValueError, match="Could not extract text from PDF page 2"):
        client.fetch_pdf("https://example.com/reports/report.pdf")
