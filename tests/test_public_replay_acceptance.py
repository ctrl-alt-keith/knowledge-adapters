from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.public_pdf.client import PublicPdfDocument
from knowledge_adapters.public_replay_acceptance import (
    DORA_ROI_2026_PDF_URL,
    MEANINGFULTECH_URL,
    PublicReplayAcceptanceError,
    assert_public_source_replay_acceptance,
    evaluate_public_source_replay_acceptance,
    public_source_replay_acceptance_keys,
    render_public_source_replay_acceptance_report,
)
from knowledge_adapters.public_webpage.client import PublicWebpageDocument

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "public_replay_acceptance"
    / "source_acceptance_metadata.json"
)


def _load_fixture_cases() -> tuple[Mapping[str, object], ...]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["schema_version"] == 1
    assert payload["source"] == "known_public_source_replay_acceptance_metadata"
    cases = payload["cases"]
    assert isinstance(cases, list)
    return tuple(cast(Mapping[str, object], case) for case in cases)


SOURCE_ACCEPTANCE_CASES = _load_fixture_cases()


def test_public_replay_acceptance_fixture_area_covers_known_sources() -> None:
    case_ids = {str(case["source_key"]) for case in SOURCE_ACCEPTANCE_CASES}

    assert case_ids == set(public_source_replay_acceptance_keys())


def test_known_public_source_replay_acceptance_cases_are_stable() -> None:
    results = []
    for case in SOURCE_ACCEPTANCE_CASES:
        result = assert_public_source_replay_acceptance(
            str(case["source_key"]),
            _mapping(case, "replay_quality_metadata"),
        )
        assert result.stable is True
        results.append(result)

    report = render_public_source_replay_acceptance_report(results)
    assert "DORA 2023 public PDF: stable" in report
    assert "MeaningfulTech webpage: stable" in report
    assert "DORA ROI 2026 public PDF: stable" in report
    assert "deterministic cleanup count" in report
    assert "remaining artifact count" in report


def test_public_replay_acceptance_fails_when_expected_cleanup_disappears() -> None:
    metadata = _metadata_by_source_key("dora_roi_2026_public_pdf")
    cleanup = _nested_mapping(
        metadata,
        (
            "replay_classification",
            "deterministic_cleanup",
            "counts_by_category",
        ),
    )
    cleanup["repeated_footer_lines_suppressed"] = 0

    result = evaluate_public_source_replay_acceptance(
        "dora_roi_2026_public_pdf",
        metadata,
    )

    assert result.stable is False
    assert any("anchored footer lines suppressed" in failure for failure in result.failures)


def test_public_replay_acceptance_fails_when_classification_changes() -> None:
    metadata = _metadata_by_source_key("meaningfultech_webpage")
    classification = _nested_mapping(metadata, ("replay_classification",))
    classification["operational_state"] = "diagnostic-only"

    try:
        assert_public_source_replay_acceptance("meaningfultech_webpage", metadata)
    except PublicReplayAcceptanceError as exc:
        assert "operational state" in str(exc)
        assert "diagnostic-only" in str(exc)
    else:
        raise AssertionError("Expected public replay acceptance to fail")


def test_public_replay_acceptance_fails_when_artifact_count_regresses() -> None:
    metadata = _metadata_by_source_key("dora_2023_public_pdf")
    reviewability = _nested_mapping(
        metadata,
        ("replay_classification", "reviewability_assessment"),
    )
    reviewability["remaining_artifact_count"] = 999

    result = evaluate_public_source_replay_acceptance("dora_2023_public_pdf", metadata)

    assert result.stable is False
    assert any("remaining artifact count" in failure for failure in result.failures)


def test_public_replay_acceptance_cli_reports_stable_source(
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_fetch_webpage(url: str) -> PublicWebpageDocument:
        assert url == MEANINGFULTECH_URL
        return PublicWebpageDocument(
            title="The Vibe Coding Illusion",
            canonical_id=url,
            source_url=url,
            fetched_at="2026-05-13T12:00:00Z",
            content="Article text.",
            replay_quality_metadata=_metadata_by_source_key("meaningfultech_webpage"),
        )

    monkeypatch.setattr(
        "knowledge_adapters.public_webpage.client.fetch_webpage",
        fake_fetch_webpage,
    )

    assert main(["public_replay_acceptance", "--source", "meaningfultech_webpage"]) == 0
    captured = capsys.readouterr()
    assert "MeaningfulTech webpage: stable" in captured.out
    assert "remaining artifact count: 0 (expected 0..2)" in captured.out


def test_public_replay_acceptance_cli_returns_nonzero_for_unexpected_source(
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    metadata = _metadata_by_source_key("dora_roi_2026_public_pdf")
    reviewability = _nested_mapping(
        metadata,
        ("replay_classification", "reviewability_assessment"),
    )
    reviewability["review_effort"] = "extended"

    def fake_fetch_pdf(url: str) -> PublicPdfDocument:
        assert url == DORA_ROI_2026_PDF_URL
        return PublicPdfDocument(
            title="DORA ROI 2026",
            canonical_id=url,
            source_url=url,
            fetched_at="2026-05-13T12:00:00Z",
            content="## Page 1\n\nReport text.",
            page_count=60,
            replay_quality_metadata=metadata,
        )

    monkeypatch.setattr("knowledge_adapters.public_pdf.client.fetch_pdf", fake_fetch_pdf)

    assert main(["public_replay_acceptance", "--source", "dora_roi_2026_public_pdf"]) == 1
    captured = capsys.readouterr()
    assert "DORA ROI 2026 public PDF: unexpected" in captured.out
    assert "review effort: expected 'focused', observed 'extended'" in captured.out


def _metadata_by_source_key(source_key: str) -> dict[str, object]:
    for case in SOURCE_ACCEPTANCE_CASES:
        if case["source_key"] == source_key:
            return copy.deepcopy(dict(_mapping(case, "replay_quality_metadata")))
    raise AssertionError(f"Unknown source acceptance case: {source_key}")


def _mapping(case: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = case[key]
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _nested_mapping(
    metadata: dict[str, object],
    path: tuple[str, ...],
) -> dict[str, object]:
    value: object = metadata
    for segment in path:
        assert isinstance(value, dict)
        value = value[segment]
    assert isinstance(value, dict)
    return cast(dict[str, object], value)
