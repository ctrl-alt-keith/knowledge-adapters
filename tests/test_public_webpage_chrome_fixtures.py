from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from knowledge_adapters.public_webpage.normalize import (
    normalize_extracted_text_with_replay_metadata,
    normalize_to_markdown,
)
from tests.artifact_assertions import parse_markdown_document

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "public_webpage"
    / "article_chrome_cases.json"
)


def _load_fixture_cases() -> tuple[Mapping[str, object], ...]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["schema_version"] == 1
    assert payload["source"] == "sanitized_public_webpage_article_chrome_cases"
    cases = payload["cases"]
    assert isinstance(cases, list)
    return tuple(cast(Mapping[str, object], case) for case in cases)


ARTICLE_CHROME_CASES = _load_fixture_cases()


def test_public_webpage_article_chrome_fixture_area_is_present() -> None:
    case_ids = {str(case["id"]) for case in ARTICLE_CHROME_CASES}

    assert case_ids == {"article_body_plus_substack_chrome"}


def test_public_webpage_chrome_suppression_keeps_article_body_with_metadata() -> None:
    case = ARTICLE_CHROME_CASES[0]

    content, metadata = normalize_extracted_text_with_replay_metadata(
        str(case["raw_content"])
    )

    assert content == case["expected_content"]
    _assert_metadata_contains(metadata, _mapping(case, "expected_metadata"))

    markdown = normalize_to_markdown(
        {
            "title": "Example Article Title",
            "canonical_id": "fixture://article",
            "source_url": "fixture://article",
            "fetched_at": "2026-05-13T12:00:00Z",
            "content": content,
            "replay_quality_metadata": metadata,
        }
    )

    assert "- candidate_status: unreviewed" in markdown
    for expected_line in _string_sequence(case, "expected_markdown_metadata_lines"):
        assert expected_line in markdown
    _title, _metadata, markdown_content = parse_markdown_document(markdown)
    assert "Article paragraph one with reviewable source material." in markdown
    assert "Subscribe Sign in" not in markdown_content
    assert "Substack is the home for great culture" not in markdown_content
    assert "Privacy" not in markdown_content


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


def _string_sequence(case: Mapping[str, object], key: str) -> list[str]:
    value = case[key]
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return cast(list[str], value)
