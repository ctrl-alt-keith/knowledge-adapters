"""Normalization logic for the public PDF/report adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from math import ceil

from knowledge_adapters.replay_quality import build_public_source_replay_classification

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
_BARE_NUMERIC_LINE_RE = re.compile(r"^\d{1,4}$")
_PAGE_NUMBERED_FOOTER_LIKE_RE = re.compile(
    r"(\bpage\s+\d+(\s+(of|/)\s+\d+)?\b|\bp\.\s*\d+(\s*/\s*\d+)?\b|"
    r"\d+\s*(of|/)\s*\d+\b|[|:/-]\s*\d+(\s*(of|/)\s*\d+)?$)",
    re.IGNORECASE,
)
_PAGE_NUMBER_LINE_RE = re.compile(
    r"^(?:page\s+|p\.\s*)?(?P<page>\d{1,4})(?:\s*(?:of|/)\s*\d{1,4})?$",
    re.IGNORECASE,
)
_VERSION_FOOTER_LINE_RE = re.compile(r"^v\.\s*\d{4}(?:[-.]\d{1,4})?$", re.IGNORECASE)
_ONE_LETTER_LINE_WRAP_PREVIOUS_CONTEXT_RE = re.compile(
    r"^(?:[\u2022*-]\s+|\d+[.)]?$|authors$)", re.IGNORECASE
)
_MEANINGFUL_NUMERIC_CONTEXT_RE = re.compile(
    r"(\b(total|metric|value|score|cost|savings|roi|result|input|output|"
    r"calculator|table|figure|formula|baseline|target|year|month|rate|percent|"
    r"percentage)\b|[$%+=*/])",
    re.IGNORECASE,
)
_MAX_FOOTER_CANDIDATE_LINES = 4
_MAX_FOOTER_LINE_LENGTH = 140
_MIN_HIGH_COVERAGE_TEXT_FOOTER_PAGES = 10
_HIGH_COVERAGE_TEXT_FOOTER_RATIO = 0.60
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
    one_letter_line_wrap_repair_count = 0
    one_letter_line_wrap_affected_page_count = 0
    for page_text in page_texts:
        normalized_page, replacement_count = _normalize_broken_url_spacing_with_count(page_text)
        normalized_page, path_repair_count = _normalize_url_path_line_wraps_with_count(
            normalized_page
        )
        normalized_page, one_letter_repair_count = (
            _normalize_one_letter_split_word_lines_with_count(normalized_page)
        )
        normalized_pages.append(normalized_page)
        url_scheme_replacement_count += replacement_count
        if replacement_count:
            url_scheme_affected_page_count += 1
        url_path_line_wrap_repair_count += path_repair_count
        if path_repair_count:
            url_path_line_wrap_affected_page_count += 1
        one_letter_line_wrap_repair_count += one_letter_repair_count
        if one_letter_repair_count:
            one_letter_line_wrap_affected_page_count += 1

    footer_page_number_diagnostics = _diagnose_footer_page_number_noise(normalized_pages)
    normalized_pages, repeated_text_footer_metadata = (
        _suppress_high_coverage_text_footer_lines_with_metadata(normalized_pages)
    )
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
        "one_letter_line_wrap_normalization": {
            "activity": "normalized" if one_letter_line_wrap_repair_count else "none",
            "repair_count": one_letter_line_wrap_repair_count,
            "affected_page_count": one_letter_line_wrap_affected_page_count,
        },
        "footer_page_number_noise_diagnostics": footer_page_number_diagnostics,
        "repeated_text_footer_suppression": repeated_text_footer_metadata,
        "repeated_footer_suppression": footer_metadata,
        "possible_layout_artifact_density": _possible_layout_artifact_density(
            normalized_pages
        ),
        "extraction_warnings": _extraction_warning_codes(empty_page_count),
    }
    metadata["replay_classification"] = _build_public_pdf_replay_classification(metadata)
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


def _normalize_one_letter_split_word_lines_with_count(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    normalized_lines: list[str] = []
    repair_count = 0
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if index + 1 >= len(lines):
            normalized_lines.append(lines[index].rstrip())
            index += 1
            continue

        next_line = lines[index + 1].strip()
        previous_line = lines[index - 1].strip() if index > 0 else ""
        if _is_one_letter_split_word_pair(previous_line, line, next_line):
            normalized_lines.append(f"{line}{next_line}")
            repair_count += 1
            index += 2
            continue

        normalized_lines.append(lines[index].rstrip())
        index += 1

    return "\n".join(normalized_lines).strip(), repair_count


def _is_one_letter_split_word_pair(
    previous_line: str, line: str, next_line: str
) -> bool:
    return bool(
        _ONE_LETTER_LINE_WRAP_PREVIOUS_CONTEXT_RE.match(previous_line)
        and len(line) == 1
        and line.isalpha()
        and next_line
        and next_line[0].islower()
        and any(character.isalpha() for character in next_line[1:])
    )


def _suppress_repeated_footer_lines(page_texts: list[str]) -> list[str]:
    return _suppress_repeated_footer_lines_with_metadata(page_texts)[0]


def _suppress_high_coverage_text_footer_lines_with_metadata(
    page_texts: list[str],
) -> tuple[list[str], dict[str, object]]:
    base_metadata: dict[str, object] = {
        "activity": "none",
        "basis": "high_coverage_trailing_text_footer_blocks",
        "min_page_count": _MIN_HIGH_COVERAGE_TEXT_FOOTER_PAGES,
        "min_coverage_ratio": f"{_HIGH_COVERAGE_TEXT_FOOTER_RATIO:.2f}",
        "suppressed_line_count": 0,
        "affected_page_count": 0,
        "detected_repeated_text_footer_block_count": 0,
        "suppressed_repeated_text_footer_block_count": 0,
        "suppressed_adjacent_page_number_line_count": 0,
        "skipped_adjacent_numeric_line_count": 0,
        "skipped_adjacent_numeric_reasons_by_code": {},
        "detected_repeated_text_footer_blocks": [],
        "skipped_adjacent_numeric_examples": [],
    }
    if len(page_texts) < _MIN_HIGH_COVERAGE_TEXT_FOOTER_PAGES:
        return [page_text.strip() for page_text in page_texts], base_metadata

    page_lines = [page_text.splitlines() for page_text in page_texts]
    trailing_entries_by_page = [
        _trailing_footer_candidate_entries(lines) for lines in page_lines
    ]
    block_pages: dict[tuple[str, ...], dict[int, tuple[int, ...]]] = {}
    for page_index, trailing_entries in enumerate(trailing_entries_by_page):
        block_signatures: list[str] = []
        block_line_indexes: list[int] = []
        for depth in range(1, _MAX_FOOTER_CANDIDATE_LINES + 1):
            entry = _trailing_entry_at_depth(trailing_entries, depth)
            if entry is None:
                break
            _entry_depth, line_index, line = entry
            signature = _repeated_text_footer_line_signature(line)
            if signature is None:
                break
            block_signatures.append(signature)
            block_line_indexes.append(line_index)
            block_pages.setdefault(tuple(block_signatures), {})[page_index] = tuple(
                block_line_indexes
            )

    min_repeated_pages = _min_high_coverage_text_footer_pages(len(page_texts))
    repeated_blocks = [
        (signature, page_to_line_indexes)
        for signature, page_to_line_indexes in block_pages.items()
        if len(page_to_line_indexes) >= min_repeated_pages
    ]
    repeated_blocks.sort(key=lambda item: (-len(item[0]), -len(item[1]), item[0]))

    indexes_to_remove: set[tuple[int, int]] = set()
    detected_blocks: list[dict[str, object]] = []
    skipped_examples: list[dict[str, object]] = []
    skipped_reasons: dict[str, int] = {}
    suppressed_adjacent_numeric_count = 0
    accepted_repeated_block_signatures: list[tuple[str, ...]] = []

    for block_signature, page_to_line_indexes in repeated_blocks:
        if len(block_signature) == 1 and not _has_accepted_longer_footer_family_signature(
            block_signature, accepted_repeated_block_signatures
        ):
            continue
        new_footer_indexes = {
            (page_index, line_index)
            for page_index, line_indexes in page_to_line_indexes.items()
            for line_index in line_indexes
            if (page_index, line_index) not in indexes_to_remove
        }
        if not new_footer_indexes:
            continue

        indexes_to_remove.update(new_footer_indexes)
        accepted_repeated_block_signatures.append(block_signature)
        adjacent_numeric_values: list[int] = []
        skipped_adjacent_numeric_count = 0
        block_length = len(block_signature)
        if block_length > 1:
            for page_index, line_indexes in page_to_line_indexes.items():
                top_line_index = min(line_indexes)
                adjacent_line_index = top_line_index - 1
                if adjacent_line_index < 0:
                    continue
                adjacent_line = page_lines[page_index][adjacent_line_index].strip()
                numeric_value = _page_number_line_value(adjacent_line)
                if numeric_value is None:
                    if re.search(r"\d", adjacent_line):
                        skipped_adjacent_numeric_count += 1
                        _increment_reason_count(
                            skipped_reasons, "non_page_number_adjacent_numeric_line", 1
                        )
                        _append_skipped_adjacent_numeric_example(
                            skipped_examples,
                            page_number=page_index + 1,
                            reason="non_page_number_adjacent_numeric_line",
                            adjacent_line=adjacent_line,
                        )
                    continue
                if numeric_value != page_index + 1:
                    skipped_adjacent_numeric_count += 1
                    _increment_reason_count(
                        skipped_reasons,
                        "adjacent_numeric_value_not_extracted_page",
                        1,
                    )
                    _append_skipped_adjacent_numeric_example(
                        skipped_examples,
                        page_number=page_index + 1,
                        reason="adjacent_numeric_value_not_extracted_page",
                        adjacent_line=adjacent_line,
                    )
                    continue
                indexes_to_remove.add((page_index, adjacent_line_index))
                adjacent_numeric_values.append(numeric_value)
                suppressed_adjacent_numeric_count += 1

        detected_blocks.append(
            {
                "footer_signature": list(reversed(block_signature)),
                "footer_depths": list(range(block_length, 0, -1)),
                "page_count": len(page_to_line_indexes),
                "suppressed_line_count": len(new_footer_indexes),
                "suppressed_adjacent_page_number_line_count": len(
                    adjacent_numeric_values
                ),
                "skipped_adjacent_numeric_line_count": skipped_adjacent_numeric_count,
                "adjacent_numeric_values": adjacent_numeric_values[:10],
            }
        )

    normalized_pages: list[str] = []
    for page_index, lines in enumerate(page_lines):
        kept_lines = [
            line.rstrip()
            for line_index, line in enumerate(lines)
            if (page_index, line_index) not in indexes_to_remove
        ]
        normalized_pages.append("\n".join(kept_lines).strip())

    if not indexes_to_remove:
        base_metadata["detected_repeated_text_footer_block_count"] = len(repeated_blocks)
        return normalized_pages, base_metadata

    return normalized_pages, {
        **base_metadata,
        "activity": "suppressed",
        "suppressed_line_count": len(indexes_to_remove),
        "affected_page_count": len(
            {page_index for page_index, _line_index in indexes_to_remove}
        ),
        "detected_repeated_text_footer_block_count": len(repeated_blocks),
        "suppressed_repeated_text_footer_block_count": len(detected_blocks),
        "suppressed_adjacent_page_number_line_count": suppressed_adjacent_numeric_count,
        "skipped_adjacent_numeric_line_count": sum(skipped_reasons.values()),
        "skipped_adjacent_numeric_reasons_by_code": skipped_reasons,
        "detected_repeated_text_footer_blocks": detected_blocks,
        "skipped_adjacent_numeric_examples": skipped_examples,
    }


def _min_high_coverage_text_footer_pages(page_count: int) -> int:
    return max(
        _MIN_HIGH_COVERAGE_TEXT_FOOTER_PAGES,
        _min_repeated_footer_pages(page_count),
        ceil(page_count * _HIGH_COVERAGE_TEXT_FOOTER_RATIO),
    )


def _has_accepted_longer_footer_family_signature(
    signature: tuple[str, ...], accepted_signatures: Sequence[tuple[str, ...]]
) -> bool:
    return any(
        len(accepted_signature) > len(signature)
        and accepted_signature[: len(signature)] == signature
        for accepted_signature in accepted_signatures
    )


def _trailing_entry_at_depth(
    trailing_entries: Sequence[tuple[int, int, str]], depth: int
) -> tuple[int, int, str] | None:
    for entry in trailing_entries:
        candidate_depth, _line_index, _line = entry
        if candidate_depth == depth:
            return entry
    return None


def _repeated_text_footer_line_signature(line: str) -> str | None:
    if _is_bare_numeric_line(line):
        return None
    if _is_page_numbered_footer_like_line(line) and not _is_version_footer_line(line):
        return None
    if not any(character.isalpha() for character in line):
        return None
    return _footer_signature(line)


def _append_skipped_adjacent_numeric_example(
    examples: list[dict[str, object]],
    *,
    page_number: int,
    reason: str,
    adjacent_line: str,
) -> None:
    if len(examples) >= 5:
        return
    examples.append(
        {
            "page_number": page_number,
            "reason": reason,
            "adjacent_excerpt": _short_diagnostic_excerpt(adjacent_line),
        }
    )


def _suppress_repeated_footer_lines_with_metadata(
    page_texts: list[str],
) -> tuple[list[str], dict[str, object]]:
    if len(page_texts) < 2:
        return [page_text.strip() for page_text in page_texts], {
            "activity": "none",
            "basis": "anchored_trailing_footer_blocks",
            "suppressed_line_count": 0,
            "affected_page_count": 0,
            "detected_footer_pattern_count": 0,
            "detected_anchored_footer_block_count": 0,
            "suppressed_anchored_footer_block_count": 0,
            "skipped_anchored_footer_block_count": 0,
            "suppressed_numeric_page_line_count": 0,
            "skipped_numeric_risk_count": 0,
            "accepted_suppressed_page_count": 0,
            "rejected_skipped_page_count": 0,
            "missing_adjacent_numeric_line_count": 0,
            "nonparseable_adjacent_numeric_line_count": 0,
            "numeric_risk_skipped_count": 0,
            "rejected_skipped_page_counts_by_reason": {},
            "detected_anchored_footer_blocks": [],
            "skipped_numeric_risk_cases": [],
            "rejected_footer_candidate_examples": [],
        }

    page_lines = [page_text.splitlines() for page_text in page_texts]
    trailing_entries_by_page = [
        _trailing_footer_candidate_entries(lines) for lines in page_lines
    ]
    anchor_candidates: dict[tuple[int, str], dict[int, int]] = {}

    for page_index, trailing_entries in enumerate(trailing_entries_by_page):
        for depth, line_index, line in trailing_entries:
            anchor_signature = _footer_anchor_signature(line)
            if anchor_signature is None:
                continue
            anchor_candidates.setdefault((depth, anchor_signature), {})[
                page_index
            ] = line_index

    min_repeated_pages = _min_repeated_footer_pages(len(page_texts))
    indexes_to_remove: set[tuple[int, int]] = set()
    detected_blocks: list[dict[str, object]] = []
    skipped_numeric_risk_cases: list[dict[str, object]] = []
    rejected_footer_candidate_examples: list[dict[str, object]] = []
    rejected_skipped_page_counts_by_reason: dict[str, int] = {}
    suppressed_numeric_page_line_count = 0
    skipped_numeric_risk_count = 0
    accepted_suppressed_page_count = 0

    for (anchor_depth, anchor_signature), page_to_anchor_index in sorted(
        anchor_candidates.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        if len(page_to_anchor_index) < min_repeated_pages:
            continue

        for numeric_depth in _adjacent_footer_depths(anchor_depth):
            numeric_occurrences: list[tuple[int, int, int]] = []
            risk_occurrences: list[tuple[int, int, int]] = []
            missing_numeric_page_indexes: list[int] = []
            nonparseable_numeric_occurrences: list[tuple[int, int, str]] = []
            risk_page_indexes: list[int] = []
            for page_index, anchor_line_index in sorted(page_to_anchor_index.items()):
                numeric_line_index = _line_index_at_trailing_depth(
                    trailing_entries_by_page[page_index], numeric_depth
                )
                if numeric_line_index is None:
                    missing_numeric_page_indexes.append(page_index)
                    continue

                numeric_line = page_lines[page_index][numeric_line_index].strip()
                numeric_value = _page_number_line_value(numeric_line)
                if numeric_value is None:
                    nonparseable_numeric_occurrences.append(
                        (page_index, numeric_line_index, numeric_line)
                    )
                    continue

                if _has_nearby_meaningful_numeric_context(
                    page_lines[page_index],
                    anchor_line_index,
                    numeric_line_index,
                ):
                    risk_occurrences.append(
                        (page_index, numeric_line_index, numeric_value)
                    )
                    risk_page_indexes.append(page_index)
                    continue

                numeric_occurrences.append(
                    (page_index, numeric_line_index, numeric_value)
                )

            if len(numeric_occurrences) < min_repeated_pages:
                if risk_page_indexes:
                    skipped_numeric_risk_count += len(risk_occurrences)
                    _increment_reason_count(
                        rejected_skipped_page_counts_by_reason,
                        "meaningful_numeric_context_near_footer_candidate",
                        len(risk_occurrences),
                    )
                    _extend_rejected_footer_candidate_examples(
                        rejected_footer_candidate_examples,
                        page_lines=page_lines,
                        page_to_anchor_index=page_to_anchor_index,
                        occurrences=risk_occurrences,
                        reason="meaningful_numeric_context_near_footer_candidate",
                    )
                    skipped_numeric_risk_cases.append(
                        {
                            "anchor_signature": anchor_signature,
                            "anchor_depth": anchor_depth,
                            "numeric_depth": numeric_depth,
                            "page_count": len(numeric_occurrences) + len(risk_occurrences),
                            "risk_page_count": len(risk_page_indexes),
                            "reason": "meaningful_numeric_context_near_footer_candidate",
                        }
                    )
                continue

            if not _numeric_values_are_in_page_order(numeric_occurrences):
                skipped_numeric_risk_count += len(numeric_occurrences)
                _increment_reason_count(
                    rejected_skipped_page_counts_by_reason,
                    "numeric_values_not_in_page_order",
                    len(numeric_occurrences),
                )
                skipped_numeric_risk_cases.append(
                    {
                        "anchor_signature": anchor_signature,
                        "anchor_depth": anchor_depth,
                        "numeric_depth": numeric_depth,
                        "page_count": len(numeric_occurrences),
                        "risk_page_count": len(numeric_occurrences),
                        "reason": "numeric_values_not_in_page_order",
                    }
                )
                continue

            footer_depths = _repeated_footer_block_depths(
                trailing_entries_by_page,
                tuple(
                    page_index
                    for page_index, _line_index, _numeric_value in numeric_occurrences
                ),
                anchor_depth,
                numeric_depth,
            )
            if not footer_depths:
                continue

            if risk_page_indexes:
                skipped_numeric_risk_count += len(risk_occurrences)
                _increment_reason_count(
                    rejected_skipped_page_counts_by_reason,
                    "meaningful_numeric_context_near_footer_candidate",
                    len(risk_occurrences),
                )
                _extend_rejected_footer_candidate_examples(
                    rejected_footer_candidate_examples,
                    page_lines=page_lines,
                    page_to_anchor_index=page_to_anchor_index,
                    occurrences=risk_occurrences,
                    reason="meaningful_numeric_context_near_footer_candidate",
                )

            for page_index, numeric_line_index, _numeric_value in numeric_occurrences:
                for footer_depth in footer_depths:
                    footer_line_index = _line_index_at_trailing_depth(
                        trailing_entries_by_page[page_index], footer_depth
                    )
                    if footer_line_index is not None:
                        indexes_to_remove.add((page_index, footer_line_index))
                indexes_to_remove.add((page_index, numeric_line_index))
            suppressed_numeric_page_line_count += len(numeric_occurrences)
            accepted_suppressed_page_count += len(numeric_occurrences)
            _increment_reason_count(
                rejected_skipped_page_counts_by_reason,
                "missing_adjacent_numeric_line",
                len(missing_numeric_page_indexes),
            )
            _increment_reason_count(
                rejected_skipped_page_counts_by_reason,
                "nonparseable_adjacent_numeric_line",
                len(nonparseable_numeric_occurrences),
            )
            _extend_missing_numeric_footer_candidate_examples(
                rejected_footer_candidate_examples,
                page_lines=page_lines,
                page_to_anchor_index=page_to_anchor_index,
                page_indexes=missing_numeric_page_indexes,
                reason="missing_adjacent_numeric_line",
            )
            _extend_nonparseable_numeric_footer_candidate_examples(
                rejected_footer_candidate_examples,
                page_lines=page_lines,
                page_to_anchor_index=page_to_anchor_index,
                occurrences=nonparseable_numeric_occurrences,
                reason="nonparseable_adjacent_numeric_line",
            )
            detected_blocks.append(
                {
                    "anchor_signature": anchor_signature,
                    "anchor_depth": anchor_depth,
                    "numeric_depth": numeric_depth,
                    "footer_depths": footer_depths,
                    "page_count": len(numeric_occurrences),
                    "numeric_values": [
                        numeric_value
                        for _page_index, _line_index, numeric_value in numeric_occurrences
                    ],
                }
            )
            break

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
        "basis": "anchored_trailing_footer_blocks",
        "suppressed_line_count": len(indexes_to_remove),
        "affected_page_count": len({page_index for page_index, _line_index in indexes_to_remove}),
        "detected_footer_pattern_count": len(detected_blocks),
        "detected_anchored_footer_block_count": (
            len(detected_blocks) + len(skipped_numeric_risk_cases)
        ),
        "suppressed_anchored_footer_block_count": len(detected_blocks),
        "skipped_anchored_footer_block_count": len(skipped_numeric_risk_cases),
        "suppressed_numeric_page_line_count": suppressed_numeric_page_line_count,
        "skipped_numeric_risk_count": skipped_numeric_risk_count,
        "accepted_suppressed_page_count": accepted_suppressed_page_count,
        "rejected_skipped_page_count": sum(rejected_skipped_page_counts_by_reason.values()),
        "missing_adjacent_numeric_line_count": rejected_skipped_page_counts_by_reason.get(
            "missing_adjacent_numeric_line", 0
        ),
        "nonparseable_adjacent_numeric_line_count": (
            rejected_skipped_page_counts_by_reason.get(
                "nonparseable_adjacent_numeric_line", 0
            )
        ),
        "numeric_risk_skipped_count": rejected_skipped_page_counts_by_reason.get(
            "meaningful_numeric_context_near_footer_candidate", 0
        ),
        "rejected_skipped_page_counts_by_reason": rejected_skipped_page_counts_by_reason,
        "detected_anchored_footer_blocks": detected_blocks,
        "skipped_numeric_risk_cases": skipped_numeric_risk_cases,
        "rejected_footer_candidate_examples": rejected_footer_candidate_examples,
    }


def _increment_reason_count(
    counts_by_reason: dict[str, int], reason: str, count: int
) -> None:
    if count:
        counts_by_reason[reason] = counts_by_reason.get(reason, 0) + count


def _extend_rejected_footer_candidate_examples(
    examples: list[dict[str, object]],
    *,
    page_lines: Sequence[Sequence[str]],
    page_to_anchor_index: Mapping[int, int],
    occurrences: Sequence[tuple[int, int, int]],
    reason: str,
) -> None:
    for page_index, numeric_line_index, _numeric_value in occurrences:
        anchor_line_index = page_to_anchor_index[page_index]
        _append_rejected_footer_candidate_example(
            examples,
            page_number=page_index + 1,
            reason=reason,
            anchor_line=page_lines[page_index][anchor_line_index],
            adjacent_line=page_lines[page_index][numeric_line_index],
        )


def _extend_missing_numeric_footer_candidate_examples(
    examples: list[dict[str, object]],
    *,
    page_lines: Sequence[Sequence[str]],
    page_to_anchor_index: Mapping[int, int],
    page_indexes: Sequence[int],
    reason: str,
) -> None:
    for page_index in page_indexes:
        anchor_line_index = page_to_anchor_index[page_index]
        _append_rejected_footer_candidate_example(
            examples,
            page_number=page_index + 1,
            reason=reason,
            anchor_line=page_lines[page_index][anchor_line_index],
            adjacent_line="",
        )


def _extend_nonparseable_numeric_footer_candidate_examples(
    examples: list[dict[str, object]],
    *,
    page_lines: Sequence[Sequence[str]],
    page_to_anchor_index: Mapping[int, int],
    occurrences: Sequence[tuple[int, int, str]],
    reason: str,
) -> None:
    for page_index, numeric_line_index, _numeric_line in occurrences:
        anchor_line_index = page_to_anchor_index[page_index]
        _append_rejected_footer_candidate_example(
            examples,
            page_number=page_index + 1,
            reason=reason,
            anchor_line=page_lines[page_index][anchor_line_index],
            adjacent_line=page_lines[page_index][numeric_line_index],
        )


def _append_rejected_footer_candidate_example(
    examples: list[dict[str, object]],
    *,
    page_number: int,
    reason: str,
    anchor_line: str,
    adjacent_line: str,
) -> None:
    if len(examples) >= 5:
        return
    example: dict[str, object] = {
        "page_number": page_number,
        "reason": reason,
        "anchor_excerpt": _short_diagnostic_excerpt(anchor_line),
    }
    if adjacent_line:
        example["adjacent_excerpt"] = _short_diagnostic_excerpt(adjacent_line)
    examples.append(example)


def _short_diagnostic_excerpt(line: str) -> str:
    excerpt = " ".join(line.strip().split())
    if len(excerpt) <= 80:
        return excerpt
    return f"{excerpt[:77].rstrip()}..."


def _trailing_footer_candidate_entries(lines: Sequence[str]) -> list[tuple[int, int, str]]:
    nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    trailing_indexes = nonempty_indexes[-_MAX_FOOTER_CANDIDATE_LINES:]
    return [
        (depth, line_index, lines[line_index].strip())
        for depth, line_index in enumerate(reversed(trailing_indexes), start=1)
    ]


def _footer_anchor_signature(line: str) -> str | None:
    if _is_bare_numeric_line(line) or _is_page_numbered_footer_like_line(line):
        return None
    if not any(character.isalpha() for character in line):
        return None
    return _footer_signature(line)


def _adjacent_footer_depths(anchor_depth: int) -> tuple[int, ...]:
    candidate_depths = (anchor_depth - 1, anchor_depth + 1)
    return tuple(
        depth for depth in candidate_depths if 1 <= depth <= _MAX_FOOTER_CANDIDATE_LINES
    )


def _line_index_at_trailing_depth(
    trailing_entries: Sequence[tuple[int, int, str]], depth: int
) -> int | None:
    for candidate_depth, line_index, _line in trailing_entries:
        if candidate_depth == depth:
            return line_index
    return None


def _repeated_footer_block_depths(
    trailing_entries_by_page: Sequence[Sequence[tuple[int, int, str]]],
    page_indexes: Sequence[int],
    anchor_depth: int,
    numeric_depth: int,
) -> list[int]:
    page_index_set = set(page_indexes)
    if numeric_depth < anchor_depth:
        candidate_depths = range(anchor_depth, _MAX_FOOTER_CANDIDATE_LINES + 1)
    else:
        candidate_depths = range(anchor_depth, 0, -1)

    footer_depths: list[int] = []
    for candidate_depth in candidate_depths:
        signatures = {
            _signature_at_trailing_depth(
                trailing_entries_by_page[page_index], candidate_depth
            )
            for page_index in page_index_set
        }
        if len(signatures) != 1:
            break
        signature = next(iter(signatures))
        if signature is None:
            break
        footer_depths.append(candidate_depth)
    return footer_depths


def _signature_at_trailing_depth(
    trailing_entries: Sequence[tuple[int, int, str]], depth: int
) -> str | None:
    for candidate_depth, _line_index, line in trailing_entries:
        if candidate_depth == depth:
            return _footer_anchor_signature(line)
    return None


def _numeric_values_are_in_page_order(
    numeric_occurrences: Sequence[tuple[int, int, int]],
) -> bool:
    numeric_values = [
        numeric_value for _page_index, _line_index, numeric_value in numeric_occurrences
    ]
    return all(
        previous_value < next_value
        for previous_value, next_value in zip(
            numeric_values, numeric_values[1:], strict=False
        )
    )


def _has_nearby_meaningful_numeric_context(
    lines: Sequence[str], anchor_line_index: int, numeric_line_index: int
) -> bool:
    first_line_index = max(0, min(anchor_line_index, numeric_line_index) - 1)
    last_line_index = min(len(lines) - 1, max(anchor_line_index, numeric_line_index) + 1)
    for line_index in range(first_line_index, last_line_index + 1):
        if line_index in {anchor_line_index, numeric_line_index}:
            continue
        if _is_meaningful_numeric_context_line(lines[line_index]):
            return True
    return False


def _diagnose_footer_page_number_noise(page_texts: Sequence[str]) -> dict[str, object]:
    page_lines = [
        [line.strip() for line in page_text.splitlines() if line.strip()]
        for page_text in page_texts
    ]
    trailing_index_sets = [
        set(range(max(0, len(lines) - _MAX_FOOTER_CANDIDATE_LINES), len(lines)))
        for lines in page_lines
    ]
    min_repeated_pages = _min_repeated_footer_pages(len(page_texts))

    trailing_signature_pages: dict[tuple[int, str], set[int]] = {}
    trailing_block_pages: dict[tuple[str, ...], set[int]] = {}
    bare_numeric_trailing_signature_pages: dict[tuple[int, str], set[int]] = {}
    bare_numeric_line_count = 0
    bare_numeric_trailing_line_count = 0
    bare_numeric_adjacent_to_numeric_content_count = 0
    mid_page_footer_like_line_count = 0

    for page_index, lines in enumerate(page_lines):
        trailing_indexes = trailing_index_sets[page_index]
        trailing_signatures: list[str] = []

        for line_index, line in enumerate(lines):
            is_trailing_candidate = line_index in trailing_indexes
            if _is_bare_numeric_line(line):
                bare_numeric_line_count += 1
                if is_trailing_candidate:
                    bare_numeric_trailing_line_count += 1
                if _has_adjacent_meaningful_numeric_context(lines, line_index):
                    bare_numeric_adjacent_to_numeric_content_count += 1

            if _is_page_numbered_footer_like_line(line) and not is_trailing_candidate:
                mid_page_footer_like_line_count += 1

            if not is_trailing_candidate:
                continue

            signature = _footer_signature(line)
            if signature is None:
                continue

            depth = len(lines) - line_index
            key = (depth, signature)
            trailing_signature_pages.setdefault(key, set()).add(page_index)
            trailing_signatures.append(signature)
            if _is_bare_numeric_line(line):
                bare_numeric_trailing_signature_pages.setdefault(key, set()).add(page_index)

        for block_length in range(1, len(trailing_signatures) + 1):
            trailing_block_pages.setdefault(
                tuple(trailing_signatures[-block_length:]), set()
            ).add(page_index)

    repeated_trailing_signature_count = sum(
        1
        for page_indexes in trailing_signature_pages.values()
        if len(page_indexes) >= min_repeated_pages
    )
    repeated_trailing_block_count = sum(
        1
        for page_indexes in trailing_block_pages.values()
        if len(page_indexes) >= min_repeated_pages
    )
    repeated_bare_numeric_trailing_signature_count = sum(
        1
        for page_indexes in bare_numeric_trailing_signature_pages.values()
        if len(page_indexes) >= min_repeated_pages
    )

    return {
        "activity": "measured",
        "basis": "post_url_normalization_pre_footer_suppression_extracted_pages",
        "candidate_window": {
            "trailing_nonempty_line_count": _MAX_FOOTER_CANDIDATE_LINES,
            "min_repeated_pages": min_repeated_pages,
        },
        "repeated_trailing_footer_block_count": repeated_trailing_block_count,
        "repeated_trailing_footer_signature_count": repeated_trailing_signature_count,
        "bare_numeric_line_count": bare_numeric_line_count,
        "bare_numeric_trailing_line_count": bare_numeric_trailing_line_count,
        "repeated_bare_numeric_trailing_signature_count": (
            repeated_bare_numeric_trailing_signature_count
        ),
        "bare_numeric_adjacent_to_numeric_content_count": (
            bare_numeric_adjacent_to_numeric_content_count
        ),
        "mid_page_footer_like_line_count": mid_page_footer_like_line_count,
        "risk_note": (
            "bare numeric lines may be page numbers or meaningful table, calculator, "
            "or report values; diagnostics do not authorize suppression"
        ),
    }


def _min_repeated_footer_pages(page_count: int) -> int:
    if page_count < 2:
        return 2
    return 2 if page_count == 2 else (page_count // 2) + 1


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


def _is_bare_numeric_line(line: str) -> bool:
    return bool(_BARE_NUMERIC_LINE_RE.fullmatch(line.strip()))


def _page_number_line_value(line: str) -> int | None:
    match = _PAGE_NUMBER_LINE_RE.fullmatch(" ".join(line.strip().split()))
    return int(match.group("page")) if match else None


def _is_page_numbered_footer_like_line(line: str) -> bool:
    return bool(_PAGE_NUMBERED_FOOTER_LIKE_RE.search(" ".join(line.strip().split())))


def _is_version_footer_line(line: str) -> bool:
    return bool(_VERSION_FOOTER_LINE_RE.fullmatch(" ".join(line.strip().split())))


def _has_adjacent_meaningful_numeric_context(lines: Sequence[str], line_index: int) -> bool:
    adjacent_lines = []
    if line_index > 0:
        adjacent_lines.append(lines[line_index - 1])
    if line_index + 1 < len(lines):
        adjacent_lines.append(lines[line_index + 1])

    return any(_is_meaningful_numeric_context_line(line) for line in adjacent_lines)


def _is_meaningful_numeric_context_line(line: str) -> bool:
    return bool(
        re.search(r"\d", line)
        and (
            _WIDE_SPACING_RE.search(line)
            or _MEANINGFUL_NUMERIC_CONTEXT_RE.search(line)
            or len(re.findall(r"\d+", line)) >= 2
        )
    )


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


def _build_public_pdf_replay_classification(
    metadata: Mapping[str, object],
) -> dict[str, object]:
    page_context = _mapping_value(metadata, "page_count_context")
    url_spacing = _mapping_value(metadata, "url_spacing_normalization")
    url_path_wrap = _mapping_value(metadata, "url_path_line_wrap_normalization")
    one_letter_wrap = _mapping_value(metadata, "one_letter_line_wrap_normalization")
    footer_page_noise = _mapping_value(metadata, "footer_page_number_noise_diagnostics")
    text_footer = _mapping_value(metadata, "repeated_text_footer_suppression")
    footer = _mapping_value(metadata, "repeated_footer_suppression")
    layout_density = _mapping_value(metadata, "possible_layout_artifact_density")
    warnings = _string_sequence(metadata.get("extraction_warnings", ()))
    empty_page_count = _int_metadata_value(page_context, "empty_page_count")
    remaining_artifact_counts = {
        "bare_numeric_lines_adjacent_to_numeric_content": _int_metadata_value(
            footer_page_noise, "bare_numeric_adjacent_to_numeric_content_count"
        ),
        "empty_pages_without_extracted_text": empty_page_count,
        "mid_page_footer_like_lines": _int_metadata_value(
            footer_page_noise, "mid_page_footer_like_line_count"
        ),
        "possible_layout_artifact_lines": _int_metadata_value(
            layout_density, "possible_artifact_line_count"
        ),
        "repeated_footer_missing_adjacent_numeric_lines": _int_metadata_value(
            footer, "missing_adjacent_numeric_line_count"
        ),
        "repeated_footer_nonparseable_adjacent_numeric_lines": _int_metadata_value(
            footer, "nonparseable_adjacent_numeric_line_count"
        ),
        "repeated_footer_numeric_risk_skipped": _int_metadata_value(
            footer, "numeric_risk_skipped_count"
        ),
        "repeated_text_footer_skipped_adjacent_numeric_lines": _int_metadata_value(
            text_footer, "skipped_adjacent_numeric_line_count"
        ),
    }
    promotion_blockers = ["public_source_candidate_requires_human_retention_review"]
    if empty_page_count:
        promotion_blockers.append("empty_pages_without_extracted_text")

    intentionally_retained_markers = [
        "full_text_extraction_retained_intentionally_for_review",
    ]
    if any(remaining_artifact_counts.values()):
        intentionally_retained_markers.append(
            "uncertain_extraction_artifacts_retained_for_review"
        )

    return build_public_source_replay_classification(
        source_type="public_pdf",
        retained_content_units=_int_metadata_value(layout_density, "line_count"),
        retained_content_unit="normalized_nonempty_text_line",
        deterministic_cleanup_counts_by_category={
            "one_letter_line_wrap_repairs": _int_metadata_value(
                one_letter_wrap, "repair_count"
            ),
            "repeated_footer_lines_suppressed": _int_metadata_value(
                footer, "suppressed_line_count"
            ),
            "repeated_text_footer_lines_suppressed": _int_metadata_value(
                text_footer, "suppressed_line_count"
            ),
            "url_path_line_wrap_repairs": _int_metadata_value(
                url_path_wrap, "repair_count"
            ),
            "url_spacing_normalizations": _int_metadata_value(
                url_spacing, "replacement_count"
            ),
        },
        remaining_artifact_counts_by_category=remaining_artifact_counts,
        known_limitation_codes=[
            *warnings,
            "public_pdf_full_text_extraction_requires_source_review",
        ],
        intentionally_retained_markers=intentionally_retained_markers,
        promotion_blocker_codes=promotion_blockers,
    )


def _render_replay_quality_metadata(metadata: Mapping[str, object]) -> str:
    classification = _mapping_value(metadata, "replay_classification")
    reviewability = _mapping_value(classification, "reviewability_assessment")
    cleanup = _mapping_value(classification, "deterministic_cleanup")
    remaining = _mapping_value(classification, "remaining_artifacts")
    page_context = _mapping_value(metadata, "page_count_context")
    url_spacing = _mapping_value(metadata, "url_spacing_normalization")
    url_path_wrap = _mapping_value(metadata, "url_path_line_wrap_normalization")
    one_letter_wrap = _mapping_value(metadata, "one_letter_line_wrap_normalization")
    footer_page_noise = _mapping_value(metadata, "footer_page_number_noise_diagnostics")
    text_footer = _mapping_value(metadata, "repeated_text_footer_suppression")
    footer = _mapping_value(metadata, "repeated_footer_suppression")
    layout_density = _mapping_value(metadata, "possible_layout_artifact_density")
    source_intent = _mapping_value(metadata, "source_intent_assessment")
    warnings = metadata.get("extraction_warnings", ())
    warning_text = (
        "; ".join(str(warning) for warning in warnings)
        if isinstance(warnings, Sequence) and not isinstance(warnings, str)
        else str(warnings)
    )
    numeric_context_risk_count = _metadata_value(
        footer_page_noise, "bare_numeric_adjacent_to_numeric_content_count"
    )
    return "\n".join(
        (
            f"- replay_quality_metadata_note: {REPLAY_QUALITY_METADATA_NOTE}",
            (
                "- replay_quality_operational_state: "
                f"{_metadata_value(classification, 'operational_state')}"
            ),
            (
                "- replay_quality_promotion_state: "
                f"{_metadata_value(classification, 'promotion_state')}"
            ),
            (
                "- replay_quality_review_effort: "
                f"{_metadata_value(reviewability, 'review_effort')}"
            ),
            (
                "- replay_quality_bounded_review_economics: "
                f"{_metadata_value(reviewability, 'bounded_review_economics')}"
            ),
            (
                "- replay_quality_deterministic_cleanup_count: "
                f"{_metadata_value(reviewability, 'deterministic_cleanup_count')}"
            ),
            (
                "- replay_quality_remaining_artifact_count: "
                f"{_metadata_value(remaining, 'total_count')}"
            ),
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
                "- replay_quality_one_letter_line_wrap_repair_count: "
                f"{_metadata_value(one_letter_wrap, 'repair_count')}"
            ),
            (
                "- replay_quality_footer_page_number_repeated_trailing_block_count: "
                f"{_metadata_value(footer_page_noise, 'repeated_trailing_footer_block_count')}"
            ),
            (
                "- replay_quality_footer_page_number_bare_numeric_line_count: "
                f"{_metadata_value(footer_page_noise, 'bare_numeric_line_count')}"
            ),
            (
                "- replay_quality_footer_page_number_numeric_context_risk_count: "
                f"{numeric_context_risk_count}"
            ),
            (
                "- replay_quality_footer_page_number_mid_page_footer_like_line_count: "
                f"{_metadata_value(footer_page_noise, 'mid_page_footer_like_line_count')}"
            ),
            (
                "- replay_quality_repeated_text_footer_suppressed_line_count: "
                f"{_metadata_value(text_footer, 'suppressed_line_count')}"
            ),
            (
                "- replay_quality_repeated_text_footer_suppressed_block_count: "
                f"{_metadata_value(text_footer, 'suppressed_repeated_text_footer_block_count')}"
            ),
            (
                "- replay_quality_repeated_text_footer_suppressed_adjacent_page_number_count: "
                f"{_metadata_value(text_footer, 'suppressed_adjacent_page_number_line_count')}"
            ),
            (
                "- replay_quality_repeated_text_footer_skipped_adjacent_numeric_count: "
                f"{_metadata_value(text_footer, 'skipped_adjacent_numeric_line_count')}"
            ),
            (
                "- replay_quality_repeated_footer_suppressed_line_count: "
                f"{_metadata_value(footer, 'suppressed_line_count')}"
            ),
            (
                "- replay_quality_repeated_footer_detected_anchored_block_count: "
                f"{_metadata_value(footer, 'detected_anchored_footer_block_count')}"
            ),
            (
                "- replay_quality_repeated_footer_suppressed_anchored_block_count: "
                f"{_metadata_value(footer, 'suppressed_anchored_footer_block_count')}"
            ),
            (
                "- replay_quality_repeated_footer_skipped_anchored_block_count: "
                f"{_metadata_value(footer, 'skipped_anchored_footer_block_count')}"
            ),
            (
                "- replay_quality_repeated_footer_suppressed_numeric_page_line_count: "
                f"{_metadata_value(footer, 'suppressed_numeric_page_line_count')}"
            ),
            (
                "- replay_quality_repeated_footer_accepted_suppressed_page_count: "
                f"{_metadata_value(footer, 'accepted_suppressed_page_count')}"
            ),
            (
                "- replay_quality_repeated_footer_rejected_skipped_page_count: "
                f"{_metadata_value(footer, 'rejected_skipped_page_count')}"
            ),
            (
                "- replay_quality_repeated_footer_missing_adjacent_numeric_line_count: "
                f"{_metadata_value(footer, 'missing_adjacent_numeric_line_count')}"
            ),
            (
                "- replay_quality_repeated_footer_nonparseable_adjacent_numeric_line_count: "
                f"{_metadata_value(footer, 'nonparseable_adjacent_numeric_line_count')}"
            ),
            (
                "- replay_quality_repeated_footer_skipped_numeric_risk_count: "
                f"{_metadata_value(footer, 'skipped_numeric_risk_count')}"
            ),
            (
                "- replay_quality_possible_layout_artifact_lines: "
                f"{_metadata_value(layout_density, 'possible_artifact_line_count')}/"
                f"{_metadata_value(layout_density, 'line_count')} "
                f"({_metadata_value(layout_density, 'possible_artifact_line_ratio')})"
            ),
            f"- replay_quality_extraction_warnings: {warning_text}",
            *(
                (
                    (
                        "- replay_quality_webpage_target_shape_assessment: "
                        f"{_metadata_value(source_intent, 'target_shape_assessment')}"
                    ),
                    (
                        "- replay_quality_webpage_likely_target_mismatch: "
                        f"{_metadata_value(source_intent, 'likely_target_mismatch')}"
                    ),
                    (
                        "- replay_quality_webpage_selected_target_url: "
                        f"{_metadata_value(source_intent, 'selected_target_url')}"
                    ),
                    (
                        "- replay_quality_webpage_target_selection_status: "
                        f"{_metadata_value(source_intent, 'target_selection_status')}"
                    ),
                    (
                        "- replay_quality_webpage_target_selection_reason: "
                        f"{_metadata_value(source_intent, 'target_selection_reason')}"
                    ),
                )
                if source_intent
                else ()
            ),
            (
                "- replay_quality_deterministic_cleanup_scope: "
                f"{_metadata_value(cleanup, 'scope')}"
            ),
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


def _int_metadata_value(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key, 0)
    return value if isinstance(value, int) else 0


def _string_sequence(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []
