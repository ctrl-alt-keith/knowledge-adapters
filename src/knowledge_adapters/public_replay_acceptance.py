"""Replay acceptance contracts for known public-source shapes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DORA_2023_PDF_URL = (
    "https://dora.dev/research/2023/dora-report/"
    "2023-dora-accelerate-state-of-devops-report.pdf"
)
DORA_ROI_2026_PDF_URL = (
    "https://services.google.com/fh/files/misc/"
    "dora-roi-of-ai-assisted-software-development-2026.pdf"
)
MEANINGFULTECH_URL = "https://meaningfultech.com/p/the-vibe-coding-illusion-why-faster"


@dataclass(frozen=True)
class NumericRangeExpectation:
    """Expected numeric range for one replay-quality metadata path."""

    label: str
    path: tuple[str, ...]
    minimum: int
    maximum: int


@dataclass(frozen=True)
class PublicSourceReplayAcceptanceSpec:
    """Stable acceptance contract for one known public source shape."""

    source_key: str
    label: str
    source_type: str
    url: str
    expected_operational_state: str
    expected_promotion_state: str
    expected_review_effort: str
    expected_review_worth_doing: bool
    expected_bounded_review_economics: bool
    numeric_ranges: tuple[NumericRangeExpectation, ...]
    required_known_limitation_codes: tuple[str, ...]
    required_intentional_retention_markers: tuple[str, ...]
    required_promotion_blocker_codes: tuple[str, ...]


@dataclass(frozen=True)
class PublicSourceReplayAcceptanceResult:
    """Evaluation result for one known public-source replay acceptance spec."""

    source_key: str
    label: str
    source_type: str
    url: str
    stable: bool
    failures: tuple[str, ...]
    summary_lines: tuple[str, ...]


class PublicReplayAcceptanceError(ValueError):
    """Raised when replay metadata does not satisfy a known-source contract."""


KNOWN_PUBLIC_SOURCE_REPLAY_ACCEPTANCE_SPECS = (
    PublicSourceReplayAcceptanceSpec(
        source_key="dora_2023_public_pdf",
        label="DORA 2023 public PDF",
        source_type="public_pdf",
        url=DORA_2023_PDF_URL,
        expected_operational_state="review-ready",
        expected_promotion_state="unsafe-to-promote",
        expected_review_effort="focused",
        expected_review_worth_doing=True,
        expected_bounded_review_economics=True,
        numeric_ranges=(
            NumericRangeExpectation(
                "retained normalized text lines",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "retained_content_units",
                ),
                3800,
                5000,
            ),
            NumericRangeExpectation(
                "deterministic cleanup count",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "deterministic_cleanup_count",
                ),
                250,
                340,
            ),
            NumericRangeExpectation(
                "remaining artifact count",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "remaining_artifact_count",
                ),
                100,
                260,
            ),
            NumericRangeExpectation(
                "URL spacing normalizations",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "url_spacing_normalizations",
                ),
                70,
                110,
            ),
            NumericRangeExpectation(
                "URL path line-wrap repairs",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "url_path_line_wrap_repairs",
                ),
                3,
                12,
            ),
            NumericRangeExpectation(
                "one-letter line-wrap repairs",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "one_letter_line_wrap_repairs",
                ),
                15,
                40,
            ),
            NumericRangeExpectation(
                "high-coverage text footer lines suppressed",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "repeated_text_footer_lines_suppressed",
                ),
                150,
                210,
            ),
            NumericRangeExpectation(
                "anchored footer lines suppressed",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "repeated_footer_lines_suppressed",
                ),
                0,
                10,
            ),
            NumericRangeExpectation(
                "possible layout artifact lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "possible_layout_artifact_lines",
                ),
                80,
                160,
            ),
            NumericRangeExpectation(
                "numeric content risk lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "bare_numeric_lines_adjacent_to_numeric_content",
                ),
                5,
                30,
            ),
            NumericRangeExpectation(
                "mid-page footer-like lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "mid_page_footer_like_lines",
                ),
                10,
                35,
            ),
            NumericRangeExpectation(
                "skipped adjacent numeric lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "repeated_text_footer_skipped_adjacent_numeric_lines",
                ),
                15,
                45,
            ),
        ),
        required_known_limitation_codes=(
            "pdf_layout_tables_figures_footnotes_headers_reading_order_may_be_incomplete",
            "scanned_image_only_pages_may_be_missing",
            "public_pdf_full_text_extraction_requires_source_review",
        ),
        required_intentional_retention_markers=(
            "full_text_extraction_retained_intentionally_for_review",
            "uncertain_extraction_artifacts_retained_for_review",
        ),
        required_promotion_blocker_codes=(
            "public_source_candidate_requires_human_retention_review",
        ),
    ),
    PublicSourceReplayAcceptanceSpec(
        source_key="meaningfultech_webpage",
        label="MeaningfulTech webpage",
        source_type="public_webpage",
        url=MEANINGFULTECH_URL,
        expected_operational_state="review-ready",
        expected_promotion_state="unsafe-to-promote",
        expected_review_effort="bounded",
        expected_review_worth_doing=True,
        expected_bounded_review_economics=True,
        numeric_ranges=(
            NumericRangeExpectation(
                "retained visible-text characters",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "retained_content_units",
                ),
                15000,
                22000,
            ),
            NumericRangeExpectation(
                "deterministic cleanup count",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "deterministic_cleanup_count",
                ),
                8,
                20,
            ),
            NumericRangeExpectation(
                "remaining artifact count",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "remaining_artifact_count",
                ),
                0,
                2,
            ),
            NumericRangeExpectation(
                "page chrome paragraphs suppressed",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "page_chrome_paragraphs_suppressed",
                ),
                8,
                20,
            ),
        ),
        required_known_limitation_codes=(
            "public_webpage_visible_text_extraction_requires_source_review",
            "links_images_tables_comments_and_publication_metadata_may_be_incomplete",
            "article_body_text_is_retained_not_summarized",
        ),
        required_intentional_retention_markers=(
            "article_body_text_retained_intentionally_for_review",
        ),
        required_promotion_blocker_codes=(
            "public_source_candidate_requires_human_retention_review",
        ),
    ),
    PublicSourceReplayAcceptanceSpec(
        source_key="dora_roi_2026_public_pdf",
        label="DORA ROI 2026 public PDF",
        source_type="public_pdf",
        url=DORA_ROI_2026_PDF_URL,
        expected_operational_state="review-ready",
        expected_promotion_state="unsafe-to-promote",
        expected_review_effort="focused",
        expected_review_worth_doing=True,
        expected_bounded_review_economics=True,
        numeric_ranges=(
            NumericRangeExpectation(
                "retained normalized text lines",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "retained_content_units",
                ),
                2800,
                3600,
            ),
            NumericRangeExpectation(
                "deterministic cleanup count",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "deterministic_cleanup_count",
                ),
                170,
                230,
            ),
            NumericRangeExpectation(
                "remaining artifact count",
                (
                    "replay_classification",
                    "reviewability_assessment",
                    "remaining_artifact_count",
                ),
                50,
                130,
            ),
            NumericRangeExpectation(
                "anchored footer lines suppressed",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "repeated_footer_lines_suppressed",
                ),
                100,
                120,
            ),
            NumericRangeExpectation(
                "URL spacing normalizations",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "url_spacing_normalizations",
                ),
                70,
                100,
            ),
            NumericRangeExpectation(
                "URL path line-wrap repairs",
                (
                    "replay_classification",
                    "deterministic_cleanup",
                    "counts_by_category",
                    "url_path_line_wrap_repairs",
                ),
                4,
                12,
            ),
            NumericRangeExpectation(
                "nonparseable adjacent numeric lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "repeated_footer_nonparseable_adjacent_numeric_lines",
                ),
                1,
                3,
            ),
            NumericRangeExpectation(
                "numeric-risk skipped footer lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "repeated_footer_numeric_risk_skipped",
                ),
                1,
                3,
            ),
            NumericRangeExpectation(
                "possible layout artifact lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "possible_layout_artifact_lines",
                ),
                5,
                30,
            ),
            NumericRangeExpectation(
                "numeric content risk lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "bare_numeric_lines_adjacent_to_numeric_content",
                ),
                40,
                80,
            ),
            NumericRangeExpectation(
                "mid-page footer-like lines",
                (
                    "replay_classification",
                    "remaining_artifacts",
                    "counts_by_category",
                    "mid_page_footer_like_lines",
                ),
                4,
                20,
            ),
        ),
        required_known_limitation_codes=(
            "pdf_layout_tables_figures_footnotes_headers_reading_order_may_be_incomplete",
            "scanned_image_only_pages_may_be_missing",
            "public_pdf_full_text_extraction_requires_source_review",
        ),
        required_intentional_retention_markers=(
            "full_text_extraction_retained_intentionally_for_review",
            "uncertain_extraction_artifacts_retained_for_review",
        ),
        required_promotion_blocker_codes=(
            "public_source_candidate_requires_human_retention_review",
        ),
    ),
)

_SPECS_BY_KEY = {
    spec.source_key: spec for spec in KNOWN_PUBLIC_SOURCE_REPLAY_ACCEPTANCE_SPECS
}


def known_public_source_replay_acceptance_specs() -> tuple[
    PublicSourceReplayAcceptanceSpec, ...
]:
    """Return the stable known-source public replay acceptance specs."""
    return KNOWN_PUBLIC_SOURCE_REPLAY_ACCEPTANCE_SPECS


def public_source_replay_acceptance_keys() -> tuple[str, ...]:
    """Return known public-source acceptance keys in display order."""
    return tuple(spec.source_key for spec in KNOWN_PUBLIC_SOURCE_REPLAY_ACCEPTANCE_SPECS)


def public_source_replay_acceptance_spec(
    source_key: str,
) -> PublicSourceReplayAcceptanceSpec:
    """Return the acceptance spec for a known source key."""
    try:
        return _SPECS_BY_KEY[source_key]
    except KeyError as exc:
        known_keys = ", ".join(public_source_replay_acceptance_keys())
        raise KeyError(
            f"Unknown public replay acceptance source {source_key!r}: {known_keys}"
        ) from exc


def evaluate_public_source_replay_acceptance(
    source_key: str,
    replay_quality_metadata: Mapping[str, object],
) -> PublicSourceReplayAcceptanceResult:
    """Evaluate replay-quality metadata against a known-source acceptance contract."""
    spec = public_source_replay_acceptance_spec(source_key)
    failures: list[str] = []
    summary_lines: list[str] = []
    classification = _mapping_at(replay_quality_metadata, ("replay_classification",))
    reviewability = _mapping_at(
        replay_quality_metadata,
        ("replay_classification", "reviewability_assessment"),
    )
    promotion_safety = _mapping_at(
        replay_quality_metadata,
        ("replay_classification", "promotion_safety"),
    )
    intentional_retention = _mapping_at(
        replay_quality_metadata,
        ("replay_classification", "intentional_retention"),
    )

    _expect_string(
        failures,
        "source type",
        classification.get("source_type"),
        spec.source_type,
    )
    _expect_string(
        failures,
        "operational state",
        classification.get("operational_state"),
        spec.expected_operational_state,
    )
    _expect_string(
        failures,
        "promotion state",
        classification.get("promotion_state"),
        spec.expected_promotion_state,
    )
    _expect_string(
        failures,
        "review effort",
        reviewability.get("review_effort"),
        spec.expected_review_effort,
    )
    _expect_bool(
        failures,
        "review worth doing",
        reviewability.get("review_worth_doing"),
        spec.expected_review_worth_doing,
    )
    _expect_bool(
        failures,
        "bounded review economics",
        reviewability.get("bounded_review_economics"),
        spec.expected_bounded_review_economics,
    )

    for expectation in spec.numeric_ranges:
        observed = _integer_at(replay_quality_metadata, expectation.path)
        if observed < expectation.minimum or observed > expectation.maximum:
            failures.append(
                f"{expectation.label}: expected {expectation.minimum}.."
                f"{expectation.maximum}, observed {observed}"
            )
        summary_lines.append(
            f"{expectation.label}: {observed} "
            f"(expected {expectation.minimum}..{expectation.maximum})"
        )

    _expect_contains_all(
        failures,
        "known limitation codes",
        _string_sequence(classification.get("known_limitation_codes")),
        spec.required_known_limitation_codes,
    )
    _expect_contains_all(
        failures,
        "intentional-retention markers",
        _string_sequence(intentional_retention.get("markers")),
        spec.required_intentional_retention_markers,
    )
    _expect_contains_all(
        failures,
        "promotion blocker codes",
        _string_sequence(promotion_safety.get("blocker_codes")),
        spec.required_promotion_blocker_codes,
    )

    return PublicSourceReplayAcceptanceResult(
        source_key=spec.source_key,
        label=spec.label,
        source_type=spec.source_type,
        url=spec.url,
        stable=not failures,
        failures=tuple(failures),
        summary_lines=tuple(summary_lines),
    )


def assert_public_source_replay_acceptance(
    source_key: str,
    replay_quality_metadata: Mapping[str, object],
) -> PublicSourceReplayAcceptanceResult:
    """Return the acceptance result or raise with all observed contract failures."""
    result = evaluate_public_source_replay_acceptance(source_key, replay_quality_metadata)
    if result.stable:
        return result
    failure_text = "\n".join(f"- {failure}" for failure in result.failures)
    raise PublicReplayAcceptanceError(
        f"{result.label} public replay acceptance failed:\n{failure_text}"
    )


def render_public_source_replay_acceptance_report(
    results: Sequence[PublicSourceReplayAcceptanceResult],
) -> str:
    """Render a compact source-level replay acceptance report."""
    lines = ["Public source replay acceptance"]
    for result in results:
        status = "stable" if result.stable else "unexpected"
        lines.extend(
            (
                "",
                f"{result.label}: {status}",
                f"  source_key: {result.source_key}",
                f"  source_type: {result.source_type}",
                f"  url: {result.url}",
            )
        )
        if result.failures:
            lines.append("  unexpected_behavior:")
            lines.extend(f"    - {failure}" for failure in result.failures)
        lines.append("  observed_acceptance_metrics:")
        lines.extend(f"    - {line}" for line in result.summary_lines)
    return "\n".join(lines)


def _mapping_at(
    mapping: Mapping[str, object],
    path: Sequence[str],
) -> Mapping[str, object]:
    value: object = mapping
    for segment in path:
        if not isinstance(value, Mapping):
            return {}
        value = value.get(segment, {})
    return value if isinstance(value, Mapping) else {}


def _integer_at(mapping: Mapping[str, object], path: Sequence[str]) -> int:
    value: object = mapping
    for segment in path:
        if not isinstance(value, Mapping):
            return 0
        value = value.get(segment, 0)
    return value if isinstance(value, int) else 0


def _expect_string(
    failures: list[str],
    label: str,
    observed: object,
    expected: str,
) -> None:
    if observed != expected:
        failures.append(f"{label}: expected {expected!r}, observed {observed!r}")


def _expect_bool(
    failures: list[str],
    label: str,
    observed: object,
    expected: bool,
) -> None:
    if observed is not expected:
        failures.append(f"{label}: expected {expected!r}, observed {observed!r}")


def _expect_contains_all(
    failures: list[str],
    label: str,
    observed: Sequence[str],
    expected_values: Sequence[str],
) -> None:
    missing = [value for value in expected_values if value not in observed]
    if missing:
        failures.append(f"{label}: missing {', '.join(missing)}")


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return tuple(str(item) for item in value)
    if value:
        return (str(value),)
    return ()
