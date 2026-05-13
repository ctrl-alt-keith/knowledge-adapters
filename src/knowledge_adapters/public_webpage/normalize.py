"""Normalization logic for the public webpage adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

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
    *,
    requested_url: str | None = None,
    resolved_url: str | None = None,
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
    source_intent_assessment = _assess_source_intent(
        extracted_paragraphs=paragraphs,
        retained_paragraphs=retained_paragraphs,
        retained_content=retained_content,
        suppressed_character_count=suppressed_character_count,
        requested_url=requested_url,
        resolved_url=resolved_url,
    )
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
        "source_intent_assessment": source_intent_assessment,
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


_FORM_FIELD_LABELS = {
    "business email",
    "business phone",
    "calling code",
    "company",
    "company name",
    "country",
    "email",
    "first name",
    "job title",
    "last name",
    "phone",
    "phone number",
    "state",
    "work email",
}
_CTA_PHRASES = {
    "access the report",
    "book a meeting",
    "contact sales",
    "download now",
    "download paper",
    "download the paper",
    "download report",
    "download the report",
    "get the report",
    "read paper",
    "read the paper",
    "request a demo",
    "request demo",
    "submit",
    "view paper",
    "view the paper",
}
_DOWNLOAD_CTA_PHRASES = {
    "access the report",
    "download now",
    "download paper",
    "download the paper",
    "download report",
    "download the report",
    "get the report",
    "read paper",
    "read the paper",
    "view paper",
    "view the paper",
}
_LEGAL_OR_CONSENT_PHRASES = {
    "by submitting this form",
    "i agree to receive",
    "privacy policy",
    "terms of service",
    "unsubscribe",
    "your personal data",
}
_CATALOG_NAVIGATION_TERMS = {
    "blog",
    "case studies",
    "contact us",
    "docs",
    "documentation",
    "events",
    "partners",
    "pricing",
    "products",
    "reports",
    "resources",
    "solutions",
    "support",
    "training",
    "webinars",
    "whitepapers",
}
_REPORT_TITLE_TERMS = {"report", "research", "state of devops", "dora"}
_COMMERCIAL_BOOK_TERMS = {
    "add to cart",
    "audiobook",
    "book",
    "buy now",
    "consulting",
    "ebook",
    "kindle",
    "paperback",
    "product",
    "purchase",
    "shop",
    "training",
    "workshop",
}
_RESEARCH_INDEX_TERMS = {
    "all research",
    "developer tools",
    "latest research",
    "octoverse",
    "publications",
    "research areas",
    "research index",
    "research portal",
    "research projects",
    "topics",
}
_CHAPTER_NAVIGATION_TERMS = {
    "chapter",
    "chapters",
    "contents",
    "part i",
    "part ii",
    "table of contents",
    "toc",
    "workbook",
}
_STABLE_RESEARCH_ASSET_URL_PATTERNS = (
    ".pdf",
    "/article/",
    "/chapter/",
    "/detail.cfm",
    "/paper/",
    "/publication/",
    "/report/",
    "/whitepaper/",
)


def _assess_source_intent(
    *,
    extracted_paragraphs: Sequence[str],
    retained_paragraphs: Sequence[str],
    retained_content: str,
    suppressed_character_count: int,
    requested_url: str | None,
    resolved_url: str | None,
) -> dict[str, object]:
    retained_character_count = len(retained_content)
    total_character_count = retained_character_count + suppressed_character_count
    retained_content_ratio = _rounded_ratio(
        retained_character_count,
        total_character_count,
    )
    substantive_paragraph_count = sum(
        1 for paragraph in retained_paragraphs if _is_substantive_body_paragraph(paragraph)
    )
    form_field_count = sum(1 for paragraph in extracted_paragraphs if _is_form_field(paragraph))
    cta_count = sum(
        1 for paragraph in extracted_paragraphs if _contains_phrase(paragraph, _CTA_PHRASES)
    )
    download_cta_count = sum(
        1
        for paragraph in extracted_paragraphs
        if _contains_phrase(paragraph, _DOWNLOAD_CTA_PHRASES)
    )
    legal_or_consent_count = sum(
        1
        for paragraph in extracted_paragraphs
        if _contains_phrase(paragraph, _LEGAL_OR_CONSENT_PHRASES)
    )
    catalog_navigation_count = sum(
        1 for paragraph in extracted_paragraphs if _is_catalog_navigation(paragraph)
    )
    report_title_mention_count = sum(
        1
        for paragraph in retained_paragraphs[:12]
        if _contains_phrase(paragraph, _REPORT_TITLE_TERMS)
    )
    short_selector_like_paragraph_count = sum(
        1 for paragraph in extracted_paragraphs if _is_selector_like_paragraph(paragraph)
    )
    commercial_book_signal_count = sum(
        1
        for paragraph in extracted_paragraphs[:30]
        if _contains_phrase(paragraph, _COMMERCIAL_BOOK_TERMS)
    )
    research_index_signal_count = sum(
        1
        for paragraph in extracted_paragraphs[:40]
        if _contains_phrase(paragraph, _RESEARCH_INDEX_TERMS)
    )
    chapter_navigation_signal_count = sum(
        1
        for paragraph in extracted_paragraphs[:50]
        if _contains_phrase(paragraph, _CHAPTER_NAVIGATION_TERMS)
    )

    possible_lead_form_page = form_field_count >= 3 and (
        download_cta_count >= 1 or legal_or_consent_count >= 1
    )
    possible_download_landing_page = download_cta_count >= 1 and (
        possible_lead_form_page
        or (substantive_paragraph_count < 3 and retained_character_count < 3000)
        or cta_count >= 3
    )
    possible_resource_catalog_page = (
        catalog_navigation_count >= 8
        and substantive_paragraph_count < 4
        and short_selector_like_paragraph_count >= 12
    )
    commercial_landing_page_detected = (
        commercial_book_signal_count >= 3
        and substantive_paragraph_count < 4
        and retained_character_count < 5000
    )
    mutable_index_page_detected = (
        research_index_signal_count >= 2
        and short_selector_like_paragraph_count >= 6
        and substantive_paragraph_count < 4
    ) or (
        possible_resource_catalog_page
        and research_index_signal_count >= 1
        and substantive_paragraph_count < 4
    )
    chapter_navigation_source_detected = (
        chapter_navigation_signal_count >= 3
        and short_selector_like_paragraph_count >= 8
        and substantive_paragraph_count < 4
    )
    historical_report_redirect_detected = _historical_report_redirect_detected(
        requested_url=requested_url,
        resolved_url=resolved_url,
    )
    stable_research_asset_detected = _stable_research_asset_detected(
        requested_url=requested_url,
        resolved_url=resolved_url,
        retained_paragraphs=retained_paragraphs,
        substantive_paragraph_count=substantive_paragraph_count,
    )
    high_chrome_to_substance_ratio = (
        total_character_count > 0
        and retained_character_count > 0
        and retained_content_ratio < 0.45
        and substantive_paragraph_count < 3
        and (
            download_cta_count > 0
            or catalog_navigation_count >= 4
            or form_field_count >= 2
        )
    )
    report_title_with_little_body = (
        report_title_mention_count > 0
        and download_cta_count >= 1
        and substantive_paragraph_count < 2
        and retained_character_count < 2500
    )
    possible_wrapper_page = (
        possible_lead_form_page
        or possible_download_landing_page
        or possible_resource_catalog_page
        or commercial_landing_page_detected
        or mutable_index_page_detected
        or high_chrome_to_substance_ratio
        or historical_report_redirect_detected
        or report_title_with_little_body
    )
    insufficient_substantive_body = (
        retained_character_count < 700 or substantive_paragraph_count < 2
    )
    likely_target_mismatch = possible_wrapper_page or chapter_navigation_source_detected or (
        insufficient_substantive_body
        and retained_character_count > 0
        and (download_cta_count > 0 or catalog_navigation_count >= 4)
    )
    substantive_content_confidence = _substantive_content_confidence(
        likely_target_mismatch=likely_target_mismatch,
        retained_character_count=retained_character_count,
        substantive_paragraph_count=substantive_paragraph_count,
    )
    reason_codes = _source_intent_reason_codes(
        possible_wrapper_page=possible_wrapper_page,
        possible_lead_form_page=possible_lead_form_page,
        possible_download_landing_page=possible_download_landing_page,
        possible_resource_catalog_page=possible_resource_catalog_page,
        commercial_landing_page_detected=commercial_landing_page_detected,
        mutable_index_page_detected=mutable_index_page_detected,
        chapter_navigation_source_detected=chapter_navigation_source_detected,
        historical_report_redirect_detected=historical_report_redirect_detected,
        stable_research_asset_detected=stable_research_asset_detected,
        insufficient_substantive_body=insufficient_substantive_body,
        high_chrome_to_substance_ratio=high_chrome_to_substance_ratio,
        report_title_with_little_body=report_title_with_little_body,
    )

    if commercial_landing_page_detected:
        target_shape_assessment = "commercial_landing_page"
    elif mutable_index_page_detected:
        target_shape_assessment = "mutable_index_page"
    elif chapter_navigation_source_detected:
        target_shape_assessment = "chapter_navigation_source"
    elif historical_report_redirect_detected and likely_target_mismatch:
        target_shape_assessment = "historical_report_redirect"
    elif stable_research_asset_detected and not likely_target_mismatch:
        target_shape_assessment = "stable_canonical_asset"
    elif likely_target_mismatch:
        target_shape_assessment = "likely_wrong_capture_target"
    elif retained_character_count == 0:
        target_shape_assessment = "no_retained_content"
    elif substantive_content_confidence in {"high", "medium"}:
        target_shape_assessment = "substantive_content_page"
    else:
        target_shape_assessment = "insufficient_substantive_body"

    return {
        "schema_version": 1,
        "target_shape_assessment": target_shape_assessment,
        "possible_wrapper_page": possible_wrapper_page,
        "possible_lead_form_page": possible_lead_form_page,
        "possible_download_landing_page": possible_download_landing_page,
        "possible_resource_catalog_page": possible_resource_catalog_page,
        "commercial_landing_page_detected": commercial_landing_page_detected,
        "mutable_index_page_detected": mutable_index_page_detected,
        "chapter_navigation_source_detected": chapter_navigation_source_detected,
        "historical_report_redirect_detected": historical_report_redirect_detected,
        "stable_research_asset_detected": stable_research_asset_detected,
        "canonical_target_resolution_status": (
            "not_resolved_yet" if likely_target_mismatch else "not_applicable"
        ),
        "canonical_source_confidence": _canonical_source_confidence(
            stable_research_asset_detected=stable_research_asset_detected,
            mutable_index_page_detected=mutable_index_page_detected,
            commercial_landing_page_detected=commercial_landing_page_detected,
            chapter_navigation_source_detected=chapter_navigation_source_detected,
            historical_report_redirect_detected=historical_report_redirect_detected,
            likely_target_mismatch=likely_target_mismatch,
        ),
        "redirect_chain_summary": _redirect_chain_summary(
            requested_url=requested_url,
            resolved_url=resolved_url,
        ),
        "substantive_content_confidence": substantive_content_confidence,
        "likely_target_mismatch": likely_target_mismatch,
        "reason_codes": reason_codes,
        "retained_content_ratio": retained_content_ratio,
        "input_url": requested_url or "",
        "resolved_url": resolved_url or "",
        "resolved_url_changed": bool(
            requested_url and resolved_url and requested_url != resolved_url
        ),
        "signal_counts": {
            "catalog_navigation_paragraphs": catalog_navigation_count,
            "cta_paragraphs": cta_count,
            "download_cta_paragraphs": download_cta_count,
            "form_field_paragraphs": form_field_count,
            "commercial_book_signal_paragraphs": commercial_book_signal_count,
            "legal_or_consent_paragraphs": legal_or_consent_count,
            "research_index_signal_paragraphs": research_index_signal_count,
            "chapter_navigation_signal_paragraphs": chapter_navigation_signal_count,
            "report_title_mentions_near_top": report_title_mention_count,
            "short_selector_like_paragraphs": short_selector_like_paragraph_count,
            "substantive_body_paragraphs": substantive_paragraph_count,
        },
    }


def _is_substantive_body_paragraph(paragraph: str) -> bool:
    text = " ".join(paragraph.split())
    if len(text) < 140:
        return False
    if len(text.split()) < 24:
        return False
    sentence_mark_count = sum(text.count(mark) for mark in (".", "?", "!"))
    return sentence_mark_count >= 2


def _is_form_field(paragraph: str) -> bool:
    normalized = _normalized_prompt_text(paragraph).replace("*", "").strip(": ")
    if normalized in _FORM_FIELD_LABELS:
        return True
    words = normalized.split()
    if len(words) <= 6:
        return any(label in normalized for label in _FORM_FIELD_LABELS)
    return False


def _contains_phrase(paragraph: str, phrases: set[str]) -> bool:
    normalized = _normalized_prompt_text(paragraph)
    return any(phrase in normalized for phrase in phrases)


def _is_catalog_navigation(paragraph: str) -> bool:
    normalized = _normalized_prompt_text(paragraph)
    if len(normalized) > 100:
        return False
    if normalized in _CATALOG_NAVIGATION_TERMS:
        return True
    return sum(1 for term in _CATALOG_NAVIGATION_TERMS if term in normalized) >= 3


def _is_selector_like_paragraph(paragraph: str) -> bool:
    text = " ".join(paragraph.split())
    if not text or len(text) > 80:
        return False
    if text.endswith((".", "?", "!")):
        return False
    return True


def _rounded_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _substantive_content_confidence(
    *,
    likely_target_mismatch: bool,
    retained_character_count: int,
    substantive_paragraph_count: int,
) -> str:
    if likely_target_mismatch or retained_character_count < 700 or substantive_paragraph_count < 2:
        return "low"
    if retained_character_count >= 8000 and substantive_paragraph_count >= 5:
        return "high"
    return "medium"


def _source_intent_reason_codes(
    *,
    possible_wrapper_page: bool,
    possible_lead_form_page: bool,
    possible_download_landing_page: bool,
    possible_resource_catalog_page: bool,
    commercial_landing_page_detected: bool,
    mutable_index_page_detected: bool,
    chapter_navigation_source_detected: bool,
    historical_report_redirect_detected: bool,
    stable_research_asset_detected: bool,
    insufficient_substantive_body: bool,
    high_chrome_to_substance_ratio: bool,
    report_title_with_little_body: bool,
) -> list[str]:
    reason_codes: list[str] = []
    if possible_wrapper_page:
        reason_codes.append("possible_wrapper_page")
    if possible_lead_form_page:
        reason_codes.append("possible_lead_form_page")
    if possible_download_landing_page:
        reason_codes.append("possible_download_landing_page")
    if possible_resource_catalog_page:
        reason_codes.append("possible_resource_catalog_page")
    if commercial_landing_page_detected:
        reason_codes.append("commercial_landing_page_detected")
    if mutable_index_page_detected:
        reason_codes.append("mutable_index_page_detected")
    if chapter_navigation_source_detected:
        reason_codes.append("chapter_navigation_source_detected")
    if historical_report_redirect_detected:
        reason_codes.append("historical_report_redirect_detected")
    if stable_research_asset_detected:
        reason_codes.append("stable_research_asset_detected")
    if insufficient_substantive_body:
        reason_codes.append("insufficient_substantive_body")
    if high_chrome_to_substance_ratio:
        reason_codes.append("high_chrome_to_substantive_content_ratio")
    if report_title_with_little_body:
        reason_codes.append("report_title_mention_with_little_adjacent_substance")
    return reason_codes


def _historical_report_redirect_detected(
    *,
    requested_url: str | None,
    resolved_url: str | None,
) -> bool:
    if not requested_url or not resolved_url or requested_url == resolved_url:
        return False
    requested = requested_url.casefold()
    resolved = resolved_url.casefold()
    requested_years = set(re.findall(r"\b20\d{2}\b", requested))
    if not requested_years:
        return False
    if not any(term in requested for term in ("report", "state-of-devops", "research")):
        return False
    return not requested_years <= set(re.findall(r"\b20\d{2}\b", resolved))


def _stable_research_asset_detected(
    *,
    requested_url: str | None,
    resolved_url: str | None,
    retained_paragraphs: Sequence[str],
    substantive_paragraph_count: int,
) -> bool:
    url_text = " ".join(url for url in (requested_url, resolved_url) if url).casefold()
    if any(pattern in url_text for pattern in _STABLE_RESEARCH_ASSET_URL_PATTERNS):
        return True
    if "doi.org/" in url_text:
        return True
    first_text = _normalized_prompt_text(" ".join(retained_paragraphs[:8]))
    if substantive_paragraph_count >= 2 and any(
        term in first_text for term in ("abstract", "doi", "published", "proceedings")
    ):
        return True
    return False


def _canonical_source_confidence(
    *,
    stable_research_asset_detected: bool,
    mutable_index_page_detected: bool,
    commercial_landing_page_detected: bool,
    chapter_navigation_source_detected: bool,
    historical_report_redirect_detected: bool,
    likely_target_mismatch: bool,
) -> str:
    if stable_research_asset_detected and not likely_target_mismatch:
        return "high"
    if historical_report_redirect_detected:
        return "low"
    if mutable_index_page_detected or commercial_landing_page_detected:
        return "none"
    if chapter_navigation_source_detected:
        return "low"
    return "none"


def _redirect_chain_summary(
    *,
    requested_url: str | None,
    resolved_url: str | None,
) -> list[dict[str, object]]:
    if not requested_url and not resolved_url:
        return []
    if requested_url and resolved_url and requested_url != resolved_url:
        return [
            {"position": 0, "role": "requested", "url": requested_url},
            {"position": 1, "role": "final", "url": resolved_url},
        ]
    url = resolved_url or requested_url or ""
    return [{"position": 0, "role": "requested_and_final", "url": url}]


def _render_replay_quality_metadata(metadata: Mapping[str, object]) -> str:
    classification = _mapping_value(metadata, "replay_classification")
    reviewability = _mapping_value(classification, "reviewability_assessment")
    cleanup = _mapping_value(classification, "deterministic_cleanup")
    remaining = _mapping_value(classification, "remaining_artifacts")
    profile = _mapping_value(metadata, "content_profile")
    boundary = _mapping_value(metadata, "extraction_boundary")
    chrome = _mapping_value(metadata, "page_chrome_suppression")
    source_intent = _mapping_value(metadata, "source_intent_assessment")
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
                "- replay_quality_webpage_target_shape_assessment: "
                f"{_metadata_value(source_intent, 'target_shape_assessment')}"
            ),
            (
                "- replay_quality_webpage_possible_wrapper_page: "
                f"{_metadata_value(source_intent, 'possible_wrapper_page')}"
            ),
            (
                "- replay_quality_webpage_possible_lead_form_page: "
                f"{_metadata_value(source_intent, 'possible_lead_form_page')}"
            ),
            (
                "- replay_quality_webpage_possible_download_landing_page: "
                f"{_metadata_value(source_intent, 'possible_download_landing_page')}"
            ),
            (
                "- replay_quality_webpage_commercial_landing_page_detected: "
                f"{_metadata_value(source_intent, 'commercial_landing_page_detected')}"
            ),
            (
                "- replay_quality_webpage_mutable_index_page_detected: "
                f"{_metadata_value(source_intent, 'mutable_index_page_detected')}"
            ),
            (
                "- replay_quality_webpage_chapter_navigation_source_detected: "
                f"{_metadata_value(source_intent, 'chapter_navigation_source_detected')}"
            ),
            (
                "- replay_quality_webpage_historical_report_redirect_detected: "
                f"{_metadata_value(source_intent, 'historical_report_redirect_detected')}"
            ),
            (
                "- replay_quality_webpage_stable_research_asset_detected: "
                f"{_metadata_value(source_intent, 'stable_research_asset_detected')}"
            ),
            (
                "- replay_quality_webpage_substantive_content_confidence: "
                f"{_metadata_value(source_intent, 'substantive_content_confidence')}"
            ),
            (
                "- replay_quality_webpage_likely_target_mismatch: "
                f"{_metadata_value(source_intent, 'likely_target_mismatch')}"
            ),
            (
                "- replay_quality_webpage_canonical_target_resolution_status: "
                f"{_metadata_value(source_intent, 'canonical_target_resolution_status')}"
            ),
            (
                "- replay_quality_webpage_canonical_source_confidence: "
                f"{_metadata_value(source_intent, 'canonical_source_confidence')}"
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
    source_intent = _mapping_value(metadata, "source_intent_assessment")
    retained_character_count = _int_metadata_value(profile, "retained_character_count")
    likely_target_mismatch = _bool_metadata_value(source_intent, "likely_target_mismatch")
    known_limitation_codes = [
        "public_webpage_visible_text_extraction_requires_source_review",
        "links_images_tables_comments_and_publication_metadata_may_be_incomplete",
        "public_webpage_source_intent_shape_requires_operator_review",
    ]
    intentionally_retained_markers: list[str] = []
    if retained_character_count:
        known_limitation_codes.append("article_body_text_is_retained_not_summarized")
        intentionally_retained_markers.append(
            "article_body_text_retained_intentionally_for_review"
        )
    else:
        known_limitation_codes.append("no_article_body_text_retained_after_cleanup")
    if likely_target_mismatch:
        known_limitation_codes.extend(
            (
                "possible_wrapper_or_gated_source_page_detected",
                "likely_target_mismatch_review_required",
            )
        )

    classification = build_public_source_replay_classification(
        source_type="public_webpage",
        retained_content_units=retained_character_count,
        retained_content_unit="retained_visible_text_character",
        deterministic_cleanup_counts_by_category={
            "page_chrome_paragraphs_suppressed": _int_metadata_value(
                chrome, "suppressed_paragraph_count"
            ),
        },
        remaining_artifact_counts_by_category={
            "possible_source_intent_mismatch": 1 if likely_target_mismatch else 0,
            "reported_remaining_webpage_chrome_artifacts": 0,
        },
        known_limitation_codes=known_limitation_codes,
        intentionally_retained_markers=intentionally_retained_markers,
    )
    if likely_target_mismatch and retained_character_count:
        _mark_classification_as_likely_wrong_target(classification, source_intent)
    return classification


def _mark_classification_as_likely_wrong_target(
    classification: dict[str, object],
    source_intent: Mapping[str, object],
) -> None:
    classification["operational_state"] = "likely-wrong-capture-target"
    classification["classification_labels"] = [
        "likely-wrong-capture-target",
        classification.get("promotion_state", ""),
    ]
    reason_codes = _string_list_value(source_intent, "reason_codes")
    classification["state_reason_codes"] = [
        "likely_target_mismatch",
        *reason_codes,
    ]
    reviewability = classification.get("reviewability_assessment", {})
    if isinstance(reviewability, dict):
        reviewability["review_effort"] = "source_target_review"
        reviewability["bounded_review_economics"] = False
    promotion_safety = classification.get("promotion_safety", {})
    if isinstance(promotion_safety, dict):
        blockers = _string_sequence_value(promotion_safety.get("blocker_codes"))
        blockers.append("likely_target_mismatch_requires_source_review")
        promotion_safety["blocker_codes"] = list(dict.fromkeys(blockers))


def _int_metadata_value(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key, 0)
    return value if isinstance(value, int) else 0


def _bool_metadata_value(metadata: Mapping[str, object], key: str) -> bool:
    value = metadata.get(key, False)
    return value if isinstance(value, bool) else False


def _string_list_value(metadata: Mapping[str, object], key: str) -> list[str]:
    return _string_sequence_value(metadata.get(key, ()))


def _string_sequence_value(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []
