"""Normalization logic for the public PDF/report adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_BROKEN_URL_SCHEME_RE = re.compile(
    r"\b(?P<scheme>https?)\s*:\s*/\s*/\s*"
    r"(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*(?::\d+)?)"
    r"(?P<path>[/#?][^\s<>()\[\]{}\"']*)?",
    re.IGNORECASE,
)
_MAX_FOOTER_CANDIDATE_LINES = 3
_MAX_FOOTER_LINE_LENGTH = 140


def normalize_extracted_pages(page_texts: Sequence[str]) -> list[str]:
    """Normalize clearly mechanical artifacts from extracted PDF page text."""
    pages = [_normalize_broken_url_spacing(page_text) for page_text in page_texts]
    return _suppress_repeated_footer_lines(pages)


def normalize_to_markdown(page: Mapping[str, object]) -> str:
    """Normalize a fetched public PDF/report into reviewable candidate markdown."""
    title = str(page.get("title", "untitled"))
    canonical_id = str(page.get("canonical_id", ""))
    source_url = str(page.get("source_url", ""))
    fetched_at = str(page.get("fetched_at", ""))
    source = str(page.get("source", "public_pdf"))
    adapter = str(page.get("adapter", "public_pdf"))
    page_count = str(page.get("page_count", ""))
    extraction_notes = str(page.get("extraction_notes", "Unreviewed candidate material."))
    content = str(page.get("content", "")).rstrip("\n")

    return f"""# {title}

## Metadata
- source: {source}
- canonical_id: {canonical_id}
- parent_id:
- source_url: {source_url}
- fetched_at: {fetched_at}
- updated_at:
- adapter: {adapter}
- candidate_status: unreviewed
- page_count: {page_count}
- extraction_notes: {extraction_notes}

## Content

> This is unreviewed candidate material generated from an external public PDF/report.

{content}
"""


def _normalize_broken_url_spacing(text: str) -> str:
    return _BROKEN_URL_SCHEME_RE.sub(_join_broken_url_scheme, text)


def _join_broken_url_scheme(match: re.Match[str]) -> str:
    path = match.group("path") or ""
    return f"{match.group('scheme')}://{match.group('host')}{path}"


def _suppress_repeated_footer_lines(page_texts: list[str]) -> list[str]:
    if len(page_texts) < 2:
        return [page_text.strip() for page_text in page_texts]

    page_lines = [page_text.splitlines() for page_text in page_texts]
    candidates: dict[tuple[int, str], set[int]] = {}
    candidate_indexes: dict[tuple[int, str], list[tuple[int, int]]] = {}

    for page_index, lines in enumerate(page_lines):
        nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
        trailing_indexes = nonempty_indexes[-_MAX_FOOTER_CANDIDATE_LINES:]
        for depth, line_index in enumerate(reversed(trailing_indexes), start=1):
            signature = _footer_signature(lines[line_index])
            if signature is None:
                continue
            key = (depth, signature)
            candidates.setdefault(key, set()).add(page_index)
            candidate_indexes.setdefault(key, []).append((page_index, line_index))

    min_repeated_pages = 2 if len(page_texts) == 2 else (len(page_texts) // 2) + 1
    indexes_to_remove: set[tuple[int, int]] = set()
    for key, page_indexes in candidates.items():
        if len(page_indexes) >= min_repeated_pages:
            indexes_to_remove.update(candidate_indexes[key])

    normalized_pages: list[str] = []
    for page_index, lines in enumerate(page_lines):
        kept_lines = [
            line.rstrip()
            for line_index, line in enumerate(lines)
            if (page_index, line_index) not in indexes_to_remove
        ]
        normalized_pages.append("\n".join(kept_lines).strip())
    return normalized_pages


def _footer_signature(line: str) -> str | None:
    cleaned = " ".join(line.strip().split())
    if not cleaned or len(cleaned) > _MAX_FOOTER_LINE_LENGTH:
        return None

    signature = cleaned.casefold()
    signature = re.sub(r"\bpage\s+\d+(\s+(of|/)\s+\d+)?\b", "page #", signature)
    signature = re.sub(r"\bp\.\s*\d+(\s*/\s*\d+)?\b", "p. #", signature)
    signature = re.sub(r"([|:/-]\s*)\d+(\s*(of|/)\s*\d+)?$", r"\1#", signature)
    signature = re.sub(r"^\d+(\s*/\s*\d+)?$", "#", signature)
    return signature
