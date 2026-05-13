from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from knowledge_adapters.public_pdf.normalize import (
    normalize_extracted_pages_with_replay_metadata,
)
from knowledge_adapters.public_pdf.normalize import normalize_to_markdown as normalize_pdf

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "public_pdf"
    / "dora_regression_cases.json"
)
REQUIRED_CASE_IDS = {
    "repeated_footer_blocks",
    "leading_space_numeric_page_lines",
    "page_number_footer_pairs",
    "repeated_trailing_footer_blocks",
    "version_footer_after_bare_page_number",
    "version_footer_missing_one_adjacent_page_number",
    "url_scheme_spacing_artifacts",
    "url_path_line_wrap_artifacts",
    "mid_page_footer_like_text",
    "in_reading_order_version_footer_pair",
    "calculator_table_numeric_traps",
    "fused_extraction_artifact_roadmap43",
}


def _load_fixture_cases() -> tuple[Mapping[str, object], ...]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["schema_version"] == 1
    assert payload["source"] == "sanitized_dora_derived_public_pdf_extraction_cases"
    cases = payload["cases"]
    assert isinstance(cases, list)
    return tuple(cast(Mapping[str, object], case) for case in cases)


def _case_tags(case: Mapping[str, object]) -> list[str]:
    value = case["tags"]
    assert isinstance(value, Sequence)
    assert not isinstance(value, str)
    assert all(isinstance(item, str) for item in value)
    return list(cast(Sequence[str], value))


DORA_REGRESSION_CASES = _load_fixture_cases()
NORMALIZATION_SUCCESS_CASES = tuple(
    case for case in DORA_REGRESSION_CASES if case["expectation"] == "normalized"
)
NO_OP_SAFETY_CASES = tuple(
    case for case in DORA_REGRESSION_CASES if case["expectation"] == "unchanged"
)
PREVIOUS_DORA_REPLAY_FAILURE_CASES = tuple(
    case
    for case in DORA_REGRESSION_CASES
    if "previous_dora_replay_failure" in _case_tags(case)
)


def test_dora_regression_fixture_area_covers_required_cases() -> None:
    case_ids = {str(case["id"]) for case in DORA_REGRESSION_CASES}

    assert REQUIRED_CASE_IDS <= case_ids
    assert len(DORA_REGRESSION_CASES) == len(case_ids)
    assert NORMALIZATION_SUCCESS_CASES
    assert NO_OP_SAFETY_CASES
    assert PREVIOUS_DORA_REPLAY_FAILURE_CASES


@pytest.mark.parametrize(
    "case",
    NORMALIZATION_SUCCESS_CASES,
    ids=lambda case: str(case["id"]),
)
def test_dora_regression_normalization_success_cases(case: Mapping[str, object]) -> None:
    normalized_pages, metadata = normalize_extracted_pages_with_replay_metadata(
        _string_sequence(case, "raw_pages")
    )

    assert normalized_pages == _string_sequence(case, "expected_pages")
    _assert_metadata_contains(metadata, _mapping(case, "expected_metadata"))


@pytest.mark.parametrize(
    "case",
    NO_OP_SAFETY_CASES,
    ids=lambda case: str(case["id"]),
)
def test_dora_regression_no_op_safety_cases(case: Mapping[str, object]) -> None:
    raw_pages = _string_sequence(case, "raw_pages")
    normalized_pages, metadata = normalize_extracted_pages_with_replay_metadata(raw_pages)

    assert normalized_pages == raw_pages
    assert normalized_pages == _string_sequence(case, "expected_pages")
    _assert_metadata_contains(metadata, _mapping(case, "expected_metadata"))


@pytest.mark.parametrize(
    "case",
    DORA_REGRESSION_CASES,
    ids=lambda case: str(case["id"]),
)
def test_dora_regression_replay_quality_metadata_contract(
    case: Mapping[str, object],
) -> None:
    normalized_pages, metadata = normalize_extracted_pages_with_replay_metadata(
        _string_sequence(case, "raw_pages")
    )

    assert metadata["metadata_scope"] == "public_pdf_replay_quality"
    assert (
        metadata["metadata_note"]
        == "informational only; does not authorize retention or promotion"
    )
    assert metadata["page_count_context"] == {
        "page_count": len(_string_sequence(case, "raw_pages")),
        "pages_with_extracted_text_count": len(
            [page for page in normalized_pages if page.strip()]
        ),
        "empty_page_count": len([page for page in normalized_pages if not page.strip()]),
    }
    assert metadata["extraction_warnings"] == [
        "pdf_layout_tables_figures_footnotes_headers_reading_order_may_be_incomplete",
        "scanned_image_only_pages_may_be_missing",
    ]

    markdown = normalize_pdf(
        {
            "title": f"Fixture {case['id']}",
            "canonical_id": f"fixture://{case['id']}",
            "source_url": f"fixture://{case['id']}",
            "page_count": len(normalized_pages),
            "content": _render_fixture_pages(normalized_pages),
            "replay_quality_metadata": metadata,
        }
    )
    assert "- candidate_status: unreviewed" in markdown
    for expected_line in _optional_string_sequence(
        case, "expected_markdown_metadata_lines"
    ):
        assert expected_line in markdown


@pytest.mark.parametrize(
    "case",
    PREVIOUS_DORA_REPLAY_FAILURE_CASES,
    ids=lambda case: str(case["id"]),
)
def test_previous_dora_replay_failures_are_fixture_backed(
    case: Mapping[str, object],
) -> None:
    normalized_pages, metadata = normalize_extracted_pages_with_replay_metadata(
        _string_sequence(case, "raw_pages")
    )

    if case["expectation"] == "normalized":
        assert normalized_pages == _string_sequence(case, "expected_pages")
    else:
        assert normalized_pages == _string_sequence(case, "raw_pages")
    _assert_metadata_contains(metadata, _mapping(case, "expected_metadata"))


def test_mixed_dora_version_footer_fixture_reports_retained_near_misses() -> None:
    case = _case_by_id("version_footer_missing_one_adjacent_page_number")

    normalized_pages, metadata = normalize_extracted_pages_with_replay_metadata(
        _string_sequence(case, "raw_pages")
    )

    assert normalized_pages[0] == "ROI calculation and\nfinancial modeling"
    assert "lead to long-term technical debt.\n3\nv. 2026.1" not in normalized_pages[1]
    assert normalized_pages[2] == (
        "Capabilities guidance\nMap your AI investment roadmap43\nv. 2026.1"
    )
    assert normalized_pages[3] == (
        'References\n4. "DORA Community."\n'
        '5. "DORA ROI of AI-assisted software development calculator."\n'
        "59\nv. 2026.1"
    )
    assert normalized_pages[4] == "Track delivery performance\nto manage risk and velocity"

    repeated_footer = _mapping(metadata, "repeated_footer_suppression")
    assert repeated_footer["accepted_suppressed_page_count"] == 3
    assert repeated_footer["rejected_skipped_page_count"] == 2
    assert repeated_footer["missing_adjacent_numeric_line_count"] == 0
    assert repeated_footer["nonparseable_adjacent_numeric_line_count"] == 1
    assert repeated_footer["numeric_risk_skipped_count"] == 1
    assert repeated_footer["rejected_skipped_page_counts_by_reason"] == {
        "meaningful_numeric_context_near_footer_candidate": 1,
        "nonparseable_adjacent_numeric_line": 1,
    }
    assert repeated_footer["rejected_footer_candidate_examples"] == [
        {
            "page_number": 4,
            "reason": "meaningful_numeric_context_near_footer_candidate",
            "anchor_excerpt": "v. 2026.1",
            "adjacent_excerpt": "59",
        },
        {
            "page_number": 3,
            "reason": "nonparseable_adjacent_numeric_line",
            "anchor_excerpt": "v. 2026.1",
            "adjacent_excerpt": "Map your AI investment roadmap43",
        },
    ]


def _assert_metadata_contains(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
    path: str = "metadata",
) -> None:
    for key, expected_value in expected.items():
        assert key in actual, f"{path}.{key} missing"
        actual_value = actual[key]
        if isinstance(expected_value, Mapping):
            assert isinstance(actual_value, Mapping), f"{path}.{key} is not a mapping"
            _assert_metadata_contains(
                cast(Mapping[str, object], actual_value),
                cast(Mapping[str, object], expected_value),
                f"{path}.{key}",
            )
            continue
        assert actual_value == expected_value, f"{path}.{key}"


def _mapping(case: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = case[key]
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _case_by_id(case_id: str) -> Mapping[str, object]:
    for case in DORA_REGRESSION_CASES:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"Unknown DORA regression fixture case: {case_id}")


def _string_sequence(case: Mapping[str, object], key: str) -> list[str]:
    value = case[key]
    assert isinstance(value, Sequence)
    assert not isinstance(value, str)
    assert all(isinstance(item, str) for item in value)
    return list(cast(Sequence[str], value))


def _optional_string_sequence(case: Mapping[str, object], key: str) -> list[str]:
    if key not in case:
        return []
    return _string_sequence(case, key)


def _render_fixture_pages(pages: Sequence[str]) -> str:
    return "\n\n".join(
        f"## Page {page_number}\n\n{page}"
        for page_number, page in enumerate(pages, start=1)
    )
