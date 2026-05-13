"""Public webpage fetching and extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from knowledge_adapters.public_sources import decode_text_response, fetch_public_url
from knowledge_adapters.public_webpage.normalize import (
    normalize_extracted_text_with_replay_metadata,
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


def fetch_webpage(url: str) -> PublicWebpageDocument:
    """Fetch and extract one public webpage URL."""
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
        extractor.markdown_text()
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized_tag = tag.lower()
        if normalized_tag == "title":
            self._in_title = True
        if normalized_tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if normalized_tag in self._BLOCK_TAGS:
            self._append_break()

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "title":
            self._in_title = False
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
