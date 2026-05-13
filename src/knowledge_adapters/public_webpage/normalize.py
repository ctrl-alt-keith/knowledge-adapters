"""Normalization logic for the public webpage adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

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
