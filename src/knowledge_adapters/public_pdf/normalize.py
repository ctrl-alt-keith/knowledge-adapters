"""Normalization logic for the public PDF/report adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

_BROKEN_URL_SCHEME_RE = re.compile(
    r"\b(?P<scheme>https?)"
    r"(?:\s+:\s*/\s*/\s*|\s*:\s+/\s*/\s*|\s*:\s*/\s+/\s*|\s*:\s*/\s*/\s+)"
    r"(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*(?::\d+)?)"
    r"(?P<path>[/#?][^\s<>()\[\]{}\"']*)?",
    re.IGNORECASE,
)
_URL_PATH_LINE_WRAP_RE = re.compile(
    r"\bhttps?://[A-Za-z0-9][A-Za-z0-9.-]*(?::\d+)?/"
    r"[^\s<>()\[\]{}\"']*-$",
    re.IGNORECASE,
)
_URL_PATH_CONTINUATION_RE = re.compile(
    r"(?=.*[-._~/%!$&'()*+,;=:@?#])[a-z0-9][a-z0-9._~%!$&'()*+,;=:@/?#-]*"
)
_WIDE_SPACING_RE = re.compile(r"\S\s{3,}\S")
_HYPHENATED_LINE_BREAK_RE = re.compile(r"[A-Za-z]{2,}-$")
_MAX_FOOTER_CANDIDATE_LINES = 3
_MAX_FOOTER_LINE_LENGTH = 140
_BASE_EXTRACTION_WARNINGS = (
    "pdf_layout_tables_figures_footnotes_headers_reading_order_may_be_incomplete",
    "scanned_image_only_pages_may_be_missing",
)
STABLE_FETCHED_AT_NOTE = "see manifest fetched_at; omitted from candidate markdown for stable diffs"
REPLAY_QUALITY_METADATA_NOTE = (
    "informational only; does not authorize retention or promotion"
)


def normalize_extracted_pages(page_texts: Sequence[str]) -> list[str]:
    """Normalize clearly mechanical artifacts from extracted PDF page text."""
    pages, _metadata = normalize_extracted_pages_with_replay_metadata(page_texts)
    return pages


def normalize_extracted_pages_with_replay_metadata(
    page_texts: Sequence[str],
) -> tuple[list[str], dict[str, object]]:
    """Normalize extracted pages and describe deterministic replay-quality signals."""
    normalized_pages: list[str] = []
    url_scheme_replacement_count = 0
    url_scheme_affected_page_count = 0
    url_path_line_wrap_repair_count = 0
    url_path_line_wrap_affected_page_count = 0
    for page_text in page_texts:
        normalized_page, replacement_count = _normalize_broken_url_spacing_with_count(page_text)
        normalized_page, path_repair_count = _normalize_url_path_line_wraps_with_count(
            normalized_page
        )
        normalized_pages.append(normalized_page)
        url_scheme_replacement_count += replacement_count
        if replacement_count:
            url_scheme_affected_page_count += 1
        url_path_line_wrap_repair_count += path_repair_count
        if path_repair_count:
            url_path_line_wrap_affected_page_count += 1

    normalized_pages, footer_metadata = _suppress_repeated_footer_lines_with_metadata(
        normalized_pages
    )
    empty_page_count = sum(1 for page_text in normalized_pages if not page_text.strip())
    page_count = len(page_texts)
    metadata: dict[str, object] = {
        "metadata_scope": "public_pdf_replay_quality",
        "metadata_note": REPLAY_QUALITY_METADATA_NOTE,
        "page_count_context": {
            "page_count": page_count,
            "pages_with_extracted_text_count": page_count - empty_page_count,
            "empty_page_count": empty_page_count,
        },
        "url_spacing_normalization": {
            "activity": "normalized" if url_scheme_replacement_count else "none",
            "replacement_count": url_scheme_replacement_count,
            "affected_page_count": url_scheme_affected_page_count,
        },
        "url_path_line_wrap_normalization": {
            "activity": "normalized" if url_path_line_wrap_repair_count else "none",
            "repair_count": url_path_line_wrap_repair_count,
            "affected_page_count": url_path_line_wrap_affected_page_count,
        },
        "repeated_footer_suppression": footer_metadata,
        "possible_layout_artifact_density": _possible_layout_artifact_density(
            normalized_pages
        ),
        "extraction_warnings": _extraction_warning_codes(empty_page_count),
    }
    return normalized_pages, metadata


def normalize_to_markdown(page: Mapping[str, object]) -> str:
    """Normalize a fetched public PDF/report into reviewable candidate markdown."""
    title = str(page.get("title", "untitled"))
    canonical_id = str(page.get("canonical_id", ""))
    source_url = str(page.get("source_url", ""))
    source = str(page.get("source", "public_pdf"))
    adapter = str(page.get("adapter", "public_pdf"))
    page_count = str(page.get("page_count", ""))
    extraction_notes = str(page.get("extraction_notes", "Unreviewed candidate material."))
    replay_quality_metadata = page.get("replay_quality_metadata")
    replay_quality_lines = (
        _render_replay_quality_metadata(replay_quality_metadata)
        if isinstance(replay_quality_metadata, Mapping) and replay_quality_metadata
        else ""
    )
    content = str(page.get("content", "")).rstrip("\n")

    return f"""# {title}

## Metadata
- source: {source}
- canonical_id: {canonical_id}
- parent_id:
- source_url: {source_url}
- fetched_at: {STABLE_FETCHED_AT_NOTE}
- updated_at:
- adapter: {adapter}
- candidate_status: unreviewed
- page_count: {page_count}
- extraction_notes: {extraction_notes}
{replay_quality_lines}

## Content

> This is unreviewed candidate material generated from an external public PDF/report.

{content}
"""


def _normalize_broken_url_spacing(text: str) -> str:
    return _normalize_broken_url_spacing_with_count(text)[0]


def _normalize_broken_url_spacing_with_count(text: str) -> tuple[str, int]:
    return _BROKEN_URL_SCHEME_RE.subn(_join_broken_url_scheme, text)


def _join_broken_url_scheme(match: re.Match[str]) -> str:
    path = match.group("path") or ""
    return f"{match.group('scheme')}://{match.group('host')}{path}"


def _normalize_url_path_line_wraps_with_count(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    normalized_lines: list[str] = []
    repair_count = 0
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if index + 1 >= len(lines):
            normalized_lines.append(line)
            index += 1
            continue

        next_line = lines[index + 1].strip()
        if _is_url_path_line_wrap_pair(line, next_line):
            normalized_lines.append(f"{line}{next_line}")
            repair_count += 1
            index += 2
            continue

        normalized_lines.append(line)
        index += 1

    return "\n".join(normalized_lines).strip(), repair_count


def _is_url_path_line_wrap_pair(line: str, next_line: str) -> bool:
    return bool(
        next_line
        and _URL_PATH_LINE_WRAP_RE.search(line)
        and _URL_PATH_CONTINUATION_RE.fullmatch(next_line)
    )


def _suppress_repeated_footer_lines(page_texts: list[str]) -> list[str]:
    return _suppress_repeated_footer_lines_with_metadata(page_texts)[0]


def _suppress_repeated_footer_lines_with_metadata(
    page_texts: list[str],
) -> tuple[list[str], dict[str, object]]:
    if len(page_texts) < 2:
        return [page_text.strip() for page_text in page_texts], {
            "activity": "none",
            "suppressed_line_count": 0,
            "affected_page_count": 0,
            "detected_footer_pattern_count": 0,
        }

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
    detected_footer_pattern_count = 0
    for key, page_indexes in candidates.items():
        if len(page_indexes) >= min_repeated_pages:
            detected_footer_pattern_count += 1
            indexes_to_remove.update(candidate_indexes[key])

    normalized_pages: list[str] = []
    for page_index, lines in enumerate(page_lines):
        kept_lines = [
            line.rstrip()
            for line_index, line in enumerate(lines)
            if (page_index, line_index) not in indexes_to_remove
        ]
        normalized_pages.append("\n".join(kept_lines).strip())
    return normalized_pages, {
        "activity": "suppressed" if indexes_to_remove else "none",
        "suppressed_line_count": len(indexes_to_remove),
        "affected_page_count": len({page_index for page_index, _line_index in indexes_to_remove}),
        "detected_footer_pattern_count": detected_footer_pattern_count,
    }


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


def _possible_layout_artifact_density(page_texts: Sequence[str]) -> dict[str, object]:
    line_count = 0
    possible_artifact_line_count = 0
    for page_text in page_texts:
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            line_count += 1
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if _is_possible_layout_artifact_line(line, next_line):
                possible_artifact_line_count += 1

    return {
        "basis": "normalized_extracted_text_lines",
        "line_count": line_count,
        "possible_artifact_line_count": possible_artifact_line_count,
        "possible_artifact_line_ratio": (
            f"{possible_artifact_line_count / line_count:.3f}" if line_count else "0.000"
        ),
    }


def _is_possible_layout_artifact_line(line: str, next_line: str) -> bool:
    return bool(
        _WIDE_SPACING_RE.search(line)
        or (
            _HYPHENATED_LINE_BREAK_RE.search(line)
            and bool(next_line)
            and next_line[0].islower()
        )
    )


def _extraction_warning_codes(empty_page_count: int) -> list[str]:
    warnings = list(_BASE_EXTRACTION_WARNINGS)
    if empty_page_count:
        warnings.append("empty_pages_without_extracted_text")
    return warnings


def _render_replay_quality_metadata(metadata: Mapping[str, object]) -> str:
    page_context = _mapping_value(metadata, "page_count_context")
    url_spacing = _mapping_value(metadata, "url_spacing_normalization")
    url_path_wrap = _mapping_value(metadata, "url_path_line_wrap_normalization")
    footer = _mapping_value(metadata, "repeated_footer_suppression")
    layout_density = _mapping_value(metadata, "possible_layout_artifact_density")
    warnings = metadata.get("extraction_warnings", ())
    warning_text = (
        "; ".join(str(warning) for warning in warnings)
        if isinstance(warnings, Sequence) and not isinstance(warnings, str)
        else str(warnings)
    )
    return "\n".join(
        (
            f"- replay_quality_metadata_note: {REPLAY_QUALITY_METADATA_NOTE}",
            f"- replay_quality_page_count: {_metadata_value(page_context, 'page_count')}",
            (
                "- replay_quality_empty_page_count: "
                f"{_metadata_value(page_context, 'empty_page_count')}"
            ),
            (
                "- replay_quality_url_spacing_normalization_count: "
                f"{_metadata_value(url_spacing, 'replacement_count')}"
            ),
            (
                "- replay_quality_url_path_line_wrap_repair_count: "
                f"{_metadata_value(url_path_wrap, 'repair_count')}"
            ),
            (
                "- replay_quality_repeated_footer_suppressed_line_count: "
                f"{_metadata_value(footer, 'suppressed_line_count')}"
            ),
            (
                "- replay_quality_possible_layout_artifact_lines: "
                f"{_metadata_value(layout_density, 'possible_artifact_line_count')}/"
                f"{_metadata_value(layout_density, 'line_count')} "
                f"({_metadata_value(layout_density, 'possible_artifact_line_ratio')})"
            ),
            f"- replay_quality_extraction_warnings: {warning_text}",
            (
                "- replay_quality_metadata_json: "
                f"{json.dumps(dict(metadata), sort_keys=True, separators=(',', ':'))}"
            ),
        )
    )


def _mapping_value(metadata: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = metadata.get(key, {})
    return value if isinstance(value, Mapping) else {}


def _metadata_value(metadata: Mapping[str, object], key: str) -> object:
    return metadata.get(key, "")
