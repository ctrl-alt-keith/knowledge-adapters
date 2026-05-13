"""Public webpage fetching and extraction."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from typing import Literal

from knowledge_adapters.public_pdf.client import PublicPdfDocument, fetch_pdf
from knowledge_adapters.public_sources import decode_text_response, fetch_public_url
from knowledge_adapters.public_webpage.normalize import (
    normalize_extracted_text_with_replay_metadata,
)
from knowledge_adapters.public_webpage.targets import (
    PublicWebpageTargetLink,
    discover_target_links,
)

MAX_WEBPAGE_BYTES = 5_000_000
WEBPAGE_EXTRACTION_NOTES = (
    "Unreviewed candidate material. Fetched a public webpage and extracted visible text "
    "with the Python standard-library HTML parser. Scripts and styles are omitted; "
    "links, images, tables, comments, and publication metadata may be incomplete. "
    "Clearly mechanical page chrome such as subscription, sign-in, sharing, discussion, "
    "footer/legal, and platform-promotion prompts may be suppressed; article body text "
    "remains unreviewed candidate material."
)


@dataclass(frozen=True)
class PublicWebpageDocument:
    """One extracted public webpage candidate."""

    title: str
    canonical_id: str
    source_url: str
    fetched_at: str
    content: str
    replay_quality_metadata: dict[str, object] = field(default_factory=dict)
    extraction_notes: str = WEBPAGE_EXTRACTION_NOTES
    source: str = "public_webpage"
    adapter: str = "public_webpage"


PublicWebpageFetchDocument = PublicWebpageDocument | PublicPdfDocument


def fetch_webpage(url: str) -> PublicWebpageFetchDocument:
    """Fetch and extract one public webpage URL."""
    return _fetch_webpage(url, target_discovery="enabled")


def _fetch_webpage(
    url: str,
    *,
    target_discovery: Literal["enabled", "disabled"],
) -> PublicWebpageFetchDocument:
    fetched = fetch_public_url(
        url,
        accepted_content_types=("text/html", "application/xhtml+xml"),
        max_bytes=MAX_WEBPAGE_BYTES,
    )
    html = decode_text_response(fetched.content, fetched.content_charset)
    extractor = _ReadableHTMLExtractor()
    extractor.feed(html)
    extractor.close()
    title = extractor.title.strip() or fetched.final_url
    content, replay_quality_metadata = normalize_extracted_text_with_replay_metadata(
        extractor.markdown_text(),
        requested_url=fetched.url,
        resolved_url=fetched.final_url,
    )
    if target_discovery == "enabled":
        source_intent = replay_quality_metadata.get("source_intent_assessment", {})
        if isinstance(source_intent, dict):
            target_selection = discover_target_links(
                requested_url=fetched.url,
                resolved_url=fetched.final_url,
                page_title=title,
                visible_text=extractor.markdown_text(),
                observed_links=extractor.target_links(),
                raw_html=html,
                source_intent_assessment=source_intent,
            )
            source_intent.update(target_selection)
            selected_url = str(target_selection.get("selected_target_url", ""))
            selected_content_type = str(
                target_selection.get("selected_target_content_type", "")
            )
            if target_selection.get("target_selection_status") == "selected":
                return _fetch_selected_target(
                    selected_url=selected_url,
                    selected_content_type=selected_content_type,
                    source_intent_assessment=dict(source_intent),
                )
    return PublicWebpageDocument(
        title=title,
        canonical_id=fetched.final_url,
        source_url=fetched.final_url,
        fetched_at=fetched.retrieved_at,
        content=content,
        replay_quality_metadata=replay_quality_metadata,
    )


class _ReadableHTMLExtractor(HTMLParser):
    """Small readable-text extractor for untrusted public HTML."""

    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    _IGNORED_TAGS = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._ignored_depth = 0
        self._parts: list[str] = []
        self._links: list[PublicWebpageTargetLink] = []
        self._active_link_href = ""
        self._active_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if normalized_tag == "title":
            self._in_title = True
        if normalized_tag == "a":
            self._active_link_href = attr_map.get("href", "")
            self._active_link_text = []
        if normalized_tag == "link":
            href = attr_map.get("href", "")
            rel = attr_map.get("rel", "")
            if href:
                self._links.append(
                    PublicWebpageTargetLink(
                        url=href,
                        label=rel,
                        source="link_href",
                    )
                )
        if normalized_tag == "meta":
            content = attr_map.get("content", "")
            label = attr_map.get("property", "") or attr_map.get("name", "")
            if content:
                self._links.append(
                    PublicWebpageTargetLink(
                        url=content,
                        label=label,
                        source="meta_url",
                    )
                )
        if normalized_tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if normalized_tag in self._BLOCK_TAGS:
            self._append_break()

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "title":
            self._in_title = False
        if normalized_tag == "a":
            if self._active_link_href:
                self._links.append(
                    PublicWebpageTargetLink(
                        url=self._active_link_href,
                        label=" ".join(self._active_link_text),
                        source="anchor_href",
                    )
                )
            self._active_link_href = ""
            self._active_link_text = []
        if normalized_tag in self._IGNORED_TAGS and self._ignored_depth > 0:
            self._ignored_depth -= 1
            return
        if normalized_tag in self._BLOCK_TAGS:
            self._append_break()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return
        if self._active_link_href:
            self._active_link_text.append(text)
        self._parts.append(text)

    def markdown_text(self) -> str:
        """Return paragraph-oriented markdown text."""
        paragraphs: list[str] = []
        current: list[str] = []
        for part in self._parts:
            if part == "\n":
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                continue
            current.append(part)
        if current:
            paragraphs.append(" ".join(current))
        return "\n\n".join(paragraphs)

    def _append_break(self) -> None:
        if self._parts and self._parts[-1] != "\n":
            self._parts.append("\n")

    def target_links(self) -> tuple[PublicWebpageTargetLink, ...]:
        """Return page-local links and metadata URLs for bounded target discovery."""
        return tuple(self._links)


def _fetch_selected_target(
    *,
    selected_url: str,
    selected_content_type: str,
    source_intent_assessment: dict[str, object],
) -> PublicWebpageFetchDocument:
    if selected_content_type == "pdf":
        pdf_document = fetch_pdf(selected_url)
        metadata = dict(pdf_document.replay_quality_metadata)
        metadata["source_intent_assessment"] = source_intent_assessment
        return replace(pdf_document, replay_quality_metadata=metadata)
    webpage_document = _fetch_webpage(selected_url, target_discovery="disabled")
    metadata = dict(webpage_document.replay_quality_metadata)
    metadata["source_intent_assessment"] = source_intent_assessment
    return replace(webpage_document, replay_quality_metadata=metadata)
