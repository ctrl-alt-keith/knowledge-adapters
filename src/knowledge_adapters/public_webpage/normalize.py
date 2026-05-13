"""Normalization logic for the public webpage adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from knowledge_adapters.replay_quality import build_public_source_replay_classification

REPLAY_QUALITY_METADATA_NOTE = (
    "informational only; does not authorize retention or promotion"
)
_CHROME_EXACT_PARAGRAPHS_BY_REASON = {
    "subscription_sign_in_prompt": {
        "subscribe sign in",
        "sign in",
    },
    "share_prompt": {
        "share",
    },
    "comments_discussion_placeholder": {
        "comments restacks",
        "top latest",
        "no posts",
    },
    "subscription_prompt": {
        "ready for more?",
        "subscribe",
    },
    "platform_promotion": {
        "start your substack get the app",
        "substack is the home for great culture",
    },
}
_LEGAL_FOOTER_RE = re.compile(r"(©|copyright).*privacy.*terms", re.IGNORECASE)


def normalize_extracted_text_with_replay_metadata(
    content: str,
) -> tuple[str, dict[str, object]]:
    """Remove clearly mechanical webpage chrome and describe review boundaries."""
    paragraphs = [paragraph.strip() for paragraph in content.split("\n\n")]
    retained_paragraphs: list[str] = []
    suppressed_examples: list[dict[str, object]] = []
    suppressed_reasons: dict[str, int] = {}
    suppressed_character_count = 0

    for paragraph in paragraphs:
        if not paragraph:
            continue
        reason = _webpage_chrome_reason(paragraph)
        if reason is None:
            retained_paragraphs.append(paragraph)
            continue
        suppressed_character_count += len(paragraph)
        suppressed_reasons[reason] = suppressed_reasons.get(reason, 0) + 1
        if len(suppressed_examples) < 8:
            suppressed_examples.append(
                {
                    "reason": reason,
                    "excerpt": _short_diagnostic_excerpt(paragraph),
                }
            )

    retained_content = "\n\n".join(retained_paragraphs)
    metadata: dict[str, object] = {
        "metadata_scope": "public_webpage_replay_quality",
        "metadata_note": REPLAY_QUALITY_METADATA_NOTE,
        "content_profile": {
            "extracted_paragraph_count": len(
                [paragraph for paragraph in paragraphs if paragraph]
            ),
            "retained_paragraph_count": len(retained_paragraphs),
            "retained_character_count": len(retained_content),
            "article_body_text_retained_for_review": True,
        },
        "extraction_boundary": {
            "basis": "visible_text_after_deterministic_page_chrome_suppression",
            "retention_boundary_review_required": True,
            "does_not_claim_copyright_or_reuse_permission": True,
            "does_not_summarize_or_shorten_article_body": True,
        },
        "page_chrome_suppression": {
            "activity": "suppressed" if suppressed_reasons else "none",
            "suppressed_paragraph_count": sum(suppressed_reasons.values()),
            "suppressed_character_count": suppressed_character_count,
            "suppressed_reasons_by_code": suppressed_reasons,
            "suppressed_examples": suppressed_examples,
        },
    }
    metadata["replay_classification"] = _build_public_webpage_replay_classification(
        metadata
    )
    return retained_content, metadata


def normalize_to_markdown(page: Mapping[str, object]) -> str:
    """Normalize a fetched public webpage into reviewable candidate markdown."""
    title = str(page.get("title", "untitled"))
    canonical_id = str(page.get("canonical_id", ""))
    source_url = str(page.get("source_url", ""))
    fetched_at = str(page.get("fetched_at", ""))
    source = str(page.get("source", "public_webpage"))
    adapter = str(page.get("adapter", "public_webpage"))
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
- fetched_at: {fetched_at}
- updated_at:
- adapter: {adapter}
- candidate_status: unreviewed
- extraction_notes: {extraction_notes}
{replay_quality_lines}

## Content

> This is unreviewed candidate material generated from an external public source.

{content}
"""


def _webpage_chrome_reason(paragraph: str) -> str | None:
    normalized = _normalized_prompt_text(paragraph)
    for reason, prompts in _CHROME_EXACT_PARAGRAPHS_BY_REASON.items():
        if normalized in prompts:
            return reason
    if _LEGAL_FOOTER_RE.search(paragraph):
        return "footer_legal_text"
    if normalized.startswith("discussion about this post"):
        return "comments_discussion_placeholder"
    return None


def _normalized_prompt_text(paragraph: str) -> str:
    return " ".join(paragraph.casefold().split())


def _short_diagnostic_excerpt(paragraph: str) -> str:
    excerpt = " ".join(paragraph.strip().split())
    if len(excerpt) <= 80:
        return excerpt
    return f"{excerpt[:77].rstrip()}..."


def _render_replay_quality_metadata(metadata: Mapping[str, object]) -> str:
    classification = _mapping_value(metadata, "replay_classification")
    reviewability = _mapping_value(classification, "reviewability_assessment")
    cleanup = _mapping_value(classification, "deterministic_cleanup")
    remaining = _mapping_value(classification, "remaining_artifacts")
    profile = _mapping_value(metadata, "content_profile")
    boundary = _mapping_value(metadata, "extraction_boundary")
    chrome = _mapping_value(metadata, "page_chrome_suppression")
    reasons = chrome.get("suppressed_reasons_by_code", {})
    reason_text = (
        "; ".join(f"{key}={value}" for key, value in sorted(reasons.items()))
        if isinstance(reasons, Mapping) and reasons
        else "none"
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
            (
                "- replay_quality_webpage_extraction_boundary: "
                f"{_metadata_value(boundary, 'basis')}"
            ),
            (
                "- replay_quality_webpage_article_body_text_retained_for_review: "
                f"{_metadata_value(profile, 'article_body_text_retained_for_review')}"
            ),
            (
                "- replay_quality_webpage_chrome_suppressed_paragraph_count: "
                f"{_metadata_value(chrome, 'suppressed_paragraph_count')}"
            ),
            f"- replay_quality_webpage_chrome_suppressed_reasons: {reason_text}",
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


def _build_public_webpage_replay_classification(
    metadata: Mapping[str, object],
) -> dict[str, object]:
    profile = _mapping_value(metadata, "content_profile")
    chrome = _mapping_value(metadata, "page_chrome_suppression")
    retained_character_count = _int_metadata_value(profile, "retained_character_count")
    known_limitation_codes = [
        "public_webpage_visible_text_extraction_requires_source_review",
        "links_images_tables_comments_and_publication_metadata_may_be_incomplete",
    ]
    intentionally_retained_markers: list[str] = []
    if retained_character_count:
        known_limitation_codes.append("article_body_text_is_retained_not_summarized")
        intentionally_retained_markers.append(
            "article_body_text_retained_intentionally_for_review"
        )
    else:
        known_limitation_codes.append("no_article_body_text_retained_after_cleanup")

    return build_public_source_replay_classification(
        source_type="public_webpage",
        retained_content_units=retained_character_count,
        retained_content_unit="retained_visible_text_character",
        deterministic_cleanup_counts_by_category={
            "page_chrome_paragraphs_suppressed": _int_metadata_value(
                chrome, "suppressed_paragraph_count"
            ),
        },
        remaining_artifact_counts_by_category={
            "reported_remaining_webpage_chrome_artifacts": 0,
        },
        known_limitation_codes=known_limitation_codes,
        intentionally_retained_markers=intentionally_retained_markers,
    )


def _int_metadata_value(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key, 0)
    return value if isinstance(value, int) else 0
