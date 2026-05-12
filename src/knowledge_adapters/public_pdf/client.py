"""Public PDF/report fetching and extraction."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from pypdf import PdfReader

from knowledge_adapters.public_pdf.normalize import (
    normalize_extracted_pages_with_replay_metadata,
)
from knowledge_adapters.public_sources import fetch_public_url

MAX_PDF_BYTES = 50_000_000
PDF_EXTRACTION_NOTES = (
    "Unreviewed candidate material. Fetched a public PDF/report and extracted text with "
    "pypdf. PDF layout, tables, figures, footnotes, headers, reading order, and scanned "
    "image-only pages may be incomplete or missing; review against the source PDF before "
    "retaining any knowledge. Clearly mechanical extraction artifacts may be normalized: "
    "broken HTTP(S) URL scheme spacing is repaired, and short repeated trailing footer "
    "lines may be suppressed when they recur by page position."
)


@dataclass(frozen=True)
class PublicPdfDocument:
    """One extracted public PDF/report candidate."""

    title: str
    canonical_id: str
    source_url: str
    fetched_at: str
    content: str
    page_count: int
    replay_quality_metadata: dict[str, object] = field(default_factory=dict)
    extraction_notes: str = PDF_EXTRACTION_NOTES
    source: str = "public_pdf"
    adapter: str = "public_pdf"


def fetch_pdf(url: str) -> PublicPdfDocument:
    """Fetch and extract text from one public PDF URL."""
    fetched = fetch_public_url(
        url,
        accepted_content_types=("application/pdf",),
        max_bytes=MAX_PDF_BYTES,
    )
    try:
        reader = PdfReader(io.BytesIO(fetched.content))
    except Exception as exc:
        raise ValueError(
            "Could not parse PDF bytes. Verify the URL returns a valid, unencrypted PDF."
        ) from exc

    metadata = reader.metadata
    title = ""
    if metadata is not None and metadata.title:
        title = str(metadata.title).strip()
    if not title:
        title = fetched.final_url.rsplit("/", maxsplit=1)[-1] or fetched.final_url

    raw_pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise ValueError(f"Could not extract text from PDF page {index}.") from exc
        raw_pages.append(text)

    normalized_page_texts, replay_quality_metadata = (
        normalize_extracted_pages_with_replay_metadata(raw_pages)
    )
    pages = [
        f"## Page {index}\n\n{text.strip()}"
        for index, text in enumerate(normalized_page_texts, start=1)
    ]

    return PublicPdfDocument(
        title=title,
        canonical_id=fetched.final_url,
        source_url=fetched.final_url,
        fetched_at=fetched.retrieved_at,
        content="\n\n".join(pages).strip(),
        page_count=len(reader.pages),
        replay_quality_metadata=replay_quality_metadata,
    )
