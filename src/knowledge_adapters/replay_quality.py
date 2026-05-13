"""Shared replay-quality classification helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

PUBLIC_SOURCE_REVIEW_BLOCKER = "public_source_candidate_requires_human_retention_review"


def build_public_source_replay_classification(
    *,
    source_type: str,
    retained_content_units: int,
    retained_content_unit: str,
    deterministic_cleanup_counts_by_category: Mapping[str, int],
    remaining_artifact_counts_by_category: Mapping[str, int],
    known_limitation_codes: Sequence[str],
    intentionally_retained_markers: Sequence[str],
    promotion_blocker_codes: Sequence[str] = (PUBLIC_SOURCE_REVIEW_BLOCKER,),
) -> dict[str, object]:
    """Build a stable, cross-source replay classification for public candidates."""
    cleanup_counts = _ordered_count_mapping(deterministic_cleanup_counts_by_category)
    remaining_counts = _ordered_count_mapping(remaining_artifact_counts_by_category)
    deterministic_cleanup_count = sum(cleanup_counts.values())
    remaining_artifact_count = sum(remaining_counts.values())
    has_retained_content = retained_content_units > 0
    operational_state = "review-ready" if has_retained_content else "diagnostic-only"
    promotion_blockers = list(dict.fromkeys(promotion_blocker_codes))
    if not has_retained_content:
        promotion_blockers.append("no_retained_content")
    promotion_state = "unsafe-to-promote" if promotion_blockers else "promotion-capable"

    return {
        "schema_version": 1,
        "source_type": source_type,
        "operational_state": operational_state,
        "promotion_state": promotion_state,
        "classification_labels": [operational_state, promotion_state],
        "state_reason_codes": _state_reason_codes(
            has_retained_content=has_retained_content,
            remaining_artifact_count=remaining_artifact_count,
        ),
        "reviewability_assessment": {
            "review_worth_doing": has_retained_content,
            "review_effort": _review_effort(
                has_retained_content=has_retained_content,
                retained_content_units=retained_content_units,
                remaining_artifact_count=remaining_artifact_count,
            ),
            "bounded_review_economics": _has_bounded_review_economics(
                has_retained_content=has_retained_content,
                retained_content_units=retained_content_units,
                remaining_artifact_count=remaining_artifact_count,
            ),
            "retained_content_units": retained_content_units,
            "retained_content_unit": retained_content_unit,
            "deterministic_cleanup_count": deterministic_cleanup_count,
            "remaining_artifact_count": remaining_artifact_count,
        },
        "deterministic_cleanup": {
            "scope": "bounded_deterministic_only",
            "counts_by_category": cleanup_counts,
        },
        "remaining_artifacts": {
            "total_count": remaining_artifact_count,
            "counts_by_category": remaining_counts,
        },
        "known_limitation_codes": list(known_limitation_codes),
        "intentional_retention": {
            "markers": list(intentionally_retained_markers),
        },
        "promotion_safety": {
            "promotion_capable": promotion_state == "promotion-capable",
            "blocker_codes": promotion_blockers,
        },
    }


def _state_reason_codes(
    *, has_retained_content: bool, remaining_artifact_count: int
) -> list[str]:
    if not has_retained_content:
        return ["no_retained_content"]
    if remaining_artifact_count:
        return ["retained_content_with_reported_remaining_artifacts"]
    return ["retained_content_with_no_reported_artifacts"]


def _review_effort(
    *,
    has_retained_content: bool,
    retained_content_units: int,
    remaining_artifact_count: int,
) -> str:
    if not has_retained_content:
        return "not_useful"
    if remaining_artifact_count == 0:
        return "bounded"
    if remaining_artifact_count <= _focused_review_threshold(retained_content_units):
        return "focused"
    return "extended"


def _has_bounded_review_economics(
    *,
    has_retained_content: bool,
    retained_content_units: int,
    remaining_artifact_count: int,
) -> bool:
    if not has_retained_content:
        return False
    return remaining_artifact_count <= _focused_review_threshold(retained_content_units)


def _focused_review_threshold(retained_content_units: int) -> int:
    return max(5, retained_content_units // 20)


def _ordered_count_mapping(counts: Mapping[str, int]) -> dict[str, int]:
    return {key: max(0, int(counts[key])) for key in sorted(counts)}
