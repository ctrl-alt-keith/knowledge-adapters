from __future__ import annotations

from typing import Any

from pytest import MonkeyPatch

from knowledge_adapters.public_pdf.client import PublicPdfDocument
from knowledge_adapters.public_sources import FetchedPublicResource
from knowledge_adapters.public_webpage.client import PublicWebpageDocument, fetch_webpage

WRAPPER_URL = "https://cloud.example.com/devops/state-of-devops"
PDF_URL = "https://services.example.com/fh/files/misc/2025_state_of_ai_assisted_software_development.pdf"


def test_public_webpage_wrapper_with_one_clear_pdf_target_is_fetched(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_fetch_public_url(url: str, **kwargs: Any) -> FetchedPublicResource:
        calls.append(url)
        return _html_response(
            url,
            f"""
            <html>
              <head><title>2025 DORA State of AI Assisted Software Development</title></head>
              <body>
                <h1>2025 DORA State of AI-Assisted Software Development report</h1>
                <p>Bridge engineering speed and business impact.</p>
                <a href="{PDF_URL}">Download the report</a>
                <p>First name</p><p>Last name</p><p>Business email</p>
                <p>Company name</p><p>Country</p>
                <p>By submitting this form, you agree to the privacy policy.</p>
              </body>
            </html>
            """,
        )

    def fake_fetch_pdf(url: str) -> PublicPdfDocument:
        assert url == PDF_URL
        return PublicPdfDocument(
            title="2025 DORA State of AI Assisted Software Development",
            canonical_id=PDF_URL,
            source_url=PDF_URL,
            fetched_at="2026-05-13T12:00:00Z",
            content="PDF report body.",
            page_count=42,
            replay_quality_metadata={
                "replay_classification": {
                    "source_type": "public_pdf",
                    "operational_state": "review-ready",
                    "promotion_state": "unsafe-to-promote",
                }
            },
        )

    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_public_url",
        fake_fetch_public_url,
    )
    monkeypatch.setattr("knowledge_adapters.public_webpage.client.fetch_pdf", fake_fetch_pdf)

    document = fetch_webpage(WRAPPER_URL)

    assert isinstance(document, PublicPdfDocument)
    assert calls == [WRAPPER_URL]
    assert document.source_url == PDF_URL
    source_intent = document.replay_quality_metadata["source_intent_assessment"]
    assert isinstance(source_intent, dict)
    assert source_intent["target_shape_assessment"] == "likely_wrong_capture_target"
    assert source_intent["target_selection_status"] == "selected"
    assert source_intent["selected_target_url"] == PDF_URL
    assert source_intent["selected_target_content_type"] == "pdf"


def test_public_webpage_wrapper_with_no_clear_target_reports_mismatch(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_public_url",
        lambda url, **kwargs: _html_response(
            url,
            """
            <html><head><title>2025 DORA State of AI Assisted Software Development</title></head>
            <body>
              <h1>2025 DORA State of AI-Assisted Software Development report</h1>
              <p>Download the report</p>
              <p>First name</p><p>Last name</p><p>Business email</p><p>Country</p>
              <a href="https://cloud.example.com/contact">Contact sales</a>
            </body></html>
            """,
        ),
    )
    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_pdf",
        lambda url: (_ for _ in ()).throw(AssertionError("unexpected PDF fetch")),
    )

    document = fetch_webpage(WRAPPER_URL)

    assert isinstance(document, PublicWebpageDocument)
    source_intent = document.replay_quality_metadata["source_intent_assessment"]
    assert isinstance(source_intent, dict)
    assert source_intent["likely_target_mismatch"] is True
    assert source_intent["target_selection_status"] == "no_high_confidence_target"
    assert source_intent["selected_target_url"] == ""


def test_public_webpage_wrapper_with_conflicting_targets_does_not_fetch(
    monkeypatch: MonkeyPatch,
) -> None:
    second_pdf = (
        "https://services.example.com/fh/files/misc/"
        "2025_state_of_ai_assisted_delivery_report.pdf"
    )
    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_public_url",
        lambda url, **kwargs: _html_response(
            url,
            f"""
            <html><head><title>2025 DORA State of AI Assisted Software Development</title></head>
            <body>
              <h1>2025 DORA State of AI-Assisted Software Development report</h1>
              <a href="{PDF_URL}">Download the report</a>
              <a href="{second_pdf}">Download the report PDF</a>
              <p>First name</p><p>Last name</p><p>Business email</p><p>Country</p>
              <p>By submitting this form, you agree to the privacy policy.</p>
            </body></html>
            """,
        ),
    )
    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_pdf",
        lambda url: (_ for _ in ()).throw(AssertionError("unexpected PDF fetch")),
    )

    document = fetch_webpage(WRAPPER_URL)

    assert isinstance(document, PublicWebpageDocument)
    source_intent = document.replay_quality_metadata["source_intent_assessment"]
    assert isinstance(source_intent, dict)
    assert source_intent["target_selection_status"] == (
        "ambiguous_multiple_high_confidence_targets"
    )
    assert source_intent["selected_target_url"] == ""


def test_public_webpage_substantive_page_does_not_select_alternate_target(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_public_url",
        lambda url, **kwargs: _html_response(
            url,
            f"""
            <html><head><title>Example Engineering Report</title></head>
            <body>
              <h1>Example Engineering Report</h1>
              <p>This report analyzes delivery performance across many software
              organizations. It explains the survey frame and operational measures.
              The body text is long enough to look like a document section rather
              than a navigation label.</p>
              <p>The findings describe deployment frequency, change lead time,
              reliability, and recovery practices. The paragraph includes multiple
              complete sentences. It provides adjacent body substance around the
              report title without asking the reader to submit a form.</p>
              <p>The conclusion explains where the evidence is strongest and where
              additional review is needed. It distinguishes observations from
              recommendations. <a href="{PDF_URL}">Download appendix</a></p>
            </body></html>
            """,
        ),
    )
    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_pdf",
        lambda url: (_ for _ in ()).throw(AssertionError("unexpected PDF fetch")),
    )

    document = fetch_webpage(WRAPPER_URL)

    assert isinstance(document, PublicWebpageDocument)
    source_intent = document.replay_quality_metadata["source_intent_assessment"]
    assert isinstance(source_intent, dict)
    assert source_intent["likely_target_mismatch"] is False
    assert source_intent["target_selection_status"] == "not_applicable_no_target_mismatch"
    assert source_intent["selected_target_url"] == ""


def _html_response(url: str, html: str) -> FetchedPublicResource:
    return FetchedPublicResource(
        url=url,
        final_url=url,
        content=html.encode("utf-8"),
        content_type="text/html",
        content_charset="utf-8",
        retrieved_at="2026-05-13T12:00:00Z",
    )
