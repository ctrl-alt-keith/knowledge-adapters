"""Bounded target discovery for public webpage wrapper captures."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import ParseResult, parse_qs, urljoin, urlparse

from knowledge_adapters.public_sources import validate_public_http_url


@dataclass(frozen=True)
class PublicWebpageTargetLink:
    """One URL observed on the fetched page itself."""

    url: str
    label: str
    source: str


_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")
_STOPWORDS = {
    "about",
    "after",
    "and",
    "assisted",
    "cloud",
    "content",
    "development",
    "download",
    "google",
    "report",
    "resources",
    "software",
    "state",
    "the",
    "with",
}
_IDENTITY_KEEPWORDS = {
    "2025",
    "ai",
    "dora",
    "devops",
}
_REPORT_TERMS = {
    "abridged",
    "accelerate",
    "ai",
    "assisted",
    "article",
    "chapter",
    "development",
    "devops",
    "dora",
    "download",
    "paper",
    "pdf",
    "publication",
    "report",
    "research",
    "software",
    "state",
    "study",
    "workbook",
    "whitepaper",
}
_STABLE_PUBLICATION_PATH_PARTS = {
    "/article/",
    "/articles/",
    "/chapter/",
    "/chapters/",
    "/detail.cfm",
    "/download/",
    "/files/",
    "/paper/",
    "/papers/",
    "/publication/",
    "/publications/",
    "/report/",
    "/reports/",
    "/resource/",
    "/resources/",
    "/uploads/",
    "/whitepaper/",
    "/whitepapers/",
}
_REJECT_HOST_PARTS = {
    "accounts.google.com",
    "facebook.com",
    "linkedin.com",
    "policies.google.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}
_REJECT_PATH_PARTS = {
    "/privacy",
    "/terms",
    "/support",
    "/contact",
    "/pricing",
    "/docs",
    "/blog",
}


def discover_target_links(
    *,
    requested_url: str,
    resolved_url: str,
    page_title: str,
    visible_text: str,
    observed_links: Sequence[PublicWebpageTargetLink],
    raw_html: str,
    source_intent_assessment: Mapping[str, object],
) -> dict[str, object]:
    """Select one high-confidence same-page report target when it is unambiguous."""
    if _bool_value(source_intent_assessment, "commercial_landing_page_detected"):
        return _target_selection(
            status="no_selection_commercial_landing_page",
            reason="commercial_landing_page_requires_operator_source_choice",
            candidate_links=(),
            canonical_status="no_selection",
            canonical_confidence="none",
        )

    if not _bool_value(source_intent_assessment, "likely_target_mismatch"):
        return _target_selection(
            status="not_applicable_no_target_mismatch",
            reason="source_intent_assessment_did_not_flag_target_mismatch",
            candidate_links=(),
            canonical_status="not_applicable",
            canonical_confidence=_source_canonical_confidence(source_intent_assessment),
        )

    candidates = _candidate_links(
        requested_url=requested_url,
        resolved_url=resolved_url,
        page_title=page_title,
        visible_text=visible_text,
        observed_links=observed_links,
        raw_html=raw_html,
    )
    high_confidence_candidates = [
        candidate for candidate in candidates if _int_value(candidate, "confidence_score") >= 70
    ]
    if not high_confidence_candidates:
        return _target_selection(
            status="no_high_confidence_target",
            reason="no_same_page_report_asset_met_selection_guards",
            candidate_links=candidates,
            canonical_status="no_selection",
            canonical_confidence="none",
        )
    if len(high_confidence_candidates) > 1:
        return _target_selection(
            status="ambiguous_multiple_high_confidence_targets",
            reason="multiple_same_page_report_assets_met_selection_guards",
            candidate_links=candidates,
            canonical_status="ambiguous",
            canonical_confidence="low",
        )

    selected = high_confidence_candidates[0]
    return _target_selection(
        status="selected",
        reason=str(selected["selection_reason"]),
        candidate_links=candidates,
        selected_url=str(selected["url"]),
        selected_content_type=str(selected["content_type"]),
        canonical_status="selected_stable_canonical_asset",
        canonical_confidence=_candidate_confidence(selected),
    )


def embedded_target_links(raw_html: str) -> tuple[PublicWebpageTargetLink, ...]:
    """Return report-like URLs found in escaped same-page href or URL text."""
    decoded = _decode_embedded_html(raw_html)
    links: dict[str, PublicWebpageTargetLink] = {}
    for url in _URL_RE.findall(decoded):
        cleaned_url = html.unescape(url).rstrip(".,;)").replace("\\/", "/")
        if not _has_report_semantics(cleaned_url, ""):
            continue
        links[cleaned_url] = PublicWebpageTargetLink(
            url=cleaned_url,
            label="",
            source="embedded_page_url",
        )
    return tuple(links.values())


def _candidate_links(
    *,
    requested_url: str,
    resolved_url: str,
    page_title: str,
    visible_text: str,
    observed_links: Sequence[PublicWebpageTargetLink],
    raw_html: str,
) -> tuple[dict[str, object], ...]:
    page_identity = _identity_tokens(f"{page_title} {visible_text[:2000]}")
    links_by_url: dict[str, PublicWebpageTargetLink] = {}
    for link in (*observed_links, *embedded_target_links(raw_html)):
        absolute_url = _absolute_url(link.url, resolved_url)
        if not absolute_url:
            continue
        previous = links_by_url.get(absolute_url)
        if previous is not None and previous.label:
            continue
        links_by_url[absolute_url] = PublicWebpageTargetLink(
            url=absolute_url,
            label=link.label,
            source=link.source,
        )

    candidates: list[dict[str, object]] = []
    for link in links_by_url.values():
        candidate = _score_candidate_link(
            link=link,
            requested_url=requested_url,
            resolved_url=resolved_url,
            page_identity=page_identity,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -_int_value(candidate, "confidence_score"),
                str(candidate["url"]),
            ),
        )[:12]
    )


def _score_candidate_link(
    *,
    link: PublicWebpageTargetLink,
    requested_url: str,
    resolved_url: str,
    page_identity: set[str],
) -> dict[str, object] | None:
    try:
        validate_public_http_url(link.url)
    except ValueError:
        return None
    if not _allowed_host_relationship(resolved_url, link.url):
        return None
    parsed = urlparse(link.url)
    normalized_url_text = _normalized_url_text(link.url)
    label = _normalize_text(link.label)
    if _is_rejected_target(parsed):
        return None
    if not _has_report_semantics(normalized_url_text, label):
        return None

    candidate_tokens = _identity_tokens(f"{normalized_url_text} {label}")
    identity_matches = sorted(page_identity & candidate_tokens)
    if len(identity_matches) < 2 and not {"dora", "2025"} <= set(identity_matches):
        return None

    is_pdf = parsed.path.lower().endswith(".pdf")
    stable_publication_url = _is_stable_publication_url(parsed, label)
    score = 0
    reasons: list[str] = []
    if is_pdf:
        score += 48
        reasons.append("pdf_asset")
    elif stable_publication_url:
        score += 34
        reasons.append("stable_publication_url")
    elif any(term in normalized_url_text for term in ("report", "whitepaper", "download")):
        score += 28
        reasons.append("report_like_html_target")
    if link.source in {"anchor_href", "link_href", "meta_url"}:
        score += 8
        reasons.append(f"observed_in_{link.source}")
    if any(term in label for term in ("canonical", "citation_pdf_url", "og:url")):
        score += 10
        reasons.append("explicit_canonical_metadata")
    if link.source == "embedded_page_url":
        score += 6
        reasons.append("observed_in_embedded_page_url")
    if stable_publication_url:
        score += 12
        reasons.append("stable_research_asset")
    score += min(36, len(identity_matches) * 6)
    if "dora" in identity_matches:
        score += 8
    if "2025" in identity_matches:
        score += 8
    if "abridged" in normalized_url_text:
        score -= 35
        reasons.append("abridged_asset_penalty")
    if re.search(r"_(de|es|fr|id|it|ja|ko|pt-br|zh-cn|zh-tw)(\.pdf|$)", normalized_url_text):
        score -= 20
        reasons.append("localized_asset_penalty")
    if _points_back_to_requested_page(link.url, requested_url, resolved_url):
        score -= 40
        reasons.append("points_back_to_wrapper_page_penalty")
    if score < 35:
        return None

    content_type = "pdf" if is_pdf else "html"
    return {
        "url": link.url,
        "label": link.label,
        "source": link.source,
        "content_type": content_type,
        "confidence_score": score,
        "identity_matches": identity_matches,
        "stable_research_asset": stable_publication_url or is_pdf,
        "selection_reason": ",".join(reasons),
    }


def _target_selection(
    *,
    status: str,
    reason: str,
    candidate_links: Sequence[Mapping[str, object]],
    canonical_status: str,
    canonical_confidence: str,
    selected_url: str = "",
    selected_content_type: str = "",
) -> dict[str, object]:
    return {
        "canonical_target_resolution_status": canonical_status,
        "canonical_source_confidence": canonical_confidence,
        "candidate_target_links": [dict(candidate) for candidate in candidate_links],
        "selected_target_url": selected_url,
        "selected_target_content_type": selected_content_type,
        "target_selection_reason": reason,
        "target_selection_status": status,
    }


def _decode_embedded_html(raw_html: str) -> str:
    decoded = raw_html
    replacements = {
        "\\u0026": "&",
        "\\u003a": ":",
        "\\u003c": "<",
        "\\u003d": "=",
        "\\u003e": ">",
        '\\"': '"',
        "\\/": "/",
    }
    for old, new in replacements.items():
        decoded = decoded.replace(old, new)
    return html.unescape(decoded)


def _absolute_url(url: str, base_url: str) -> str:
    if not url:
        return ""
    if url.startswith("#") or url.lower().startswith(("mailto:", "tel:", "javascript:")):
        return ""
    return urljoin(base_url, html.unescape(url.strip()))


def _allowed_host_relationship(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()
    if not base_host or not candidate_host:
        return False
    if base_host == candidate_host:
        return True
    return _registrable_domain(base_host) == _registrable_domain(candidate_host)


def _registrable_domain(hostname: str) -> str:
    parts = hostname.rsplit(".", maxsplit=2)
    if len(parts) < 2:
        return hostname
    return ".".join(parts[-2:])


def _is_rejected_target(parsed_url: ParseResult) -> bool:
    hostname = str(parsed_url.hostname or "").lower()
    path = str(parsed_url.path or "").lower()
    if hostname in _REJECT_HOST_PARTS:
        return True
    if any(path_part in path for path_part in _REJECT_PATH_PARTS):
        return True
    query = parse_qs(str(getattr(parsed_url, "query", "")))
    return bool({"continue", "redirectPath"} & set(query))


def _has_report_semantics(url_text: str, label: str) -> bool:
    text = _normalize_text(f"{url_text} {label}")
    return any(term in text for term in _REPORT_TERMS)


def _is_stable_publication_url(parsed: ParseResult, label: str) -> bool:
    path = str(parsed.path or "").lower()
    query = str(parsed.query or "").lower()
    if path.endswith(".pdf"):
        return True
    if any(path_part in path for path_part in _STABLE_PUBLICATION_PATH_PARTS):
        return True
    if path.endswith("/toc") or path.endswith("/table-of-contents"):
        return True
    if path.endswith(("/toc/", "/table-of-contents/")):
        return True
    if parsed.hostname == "queue.acm.org" and path.endswith("/detail.cfm") and "id=" in query:
        return True
    normalized_label = _normalize_text(label)
    return "canonical" in normalized_label and _has_report_semantics(path, normalized_label)


def _identity_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", _normalize_text(text)))
    return {
        token
        for token in tokens
        if token in _IDENTITY_KEEPWORDS or (len(token) >= 4 and token not in _STOPWORDS)
    }


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().replace("_", " ").replace("-", " ").split())


def _normalized_url_text(url: str) -> str:
    parsed = urlparse(url)
    return _normalize_text(f"{parsed.netloc} {parsed.path} {parsed.query}")


def _points_back_to_requested_page(
    candidate_url: str,
    requested_url: str,
    resolved_url: str,
) -> bool:
    candidate = urlparse(candidate_url)
    for url in (requested_url, resolved_url):
        parsed = urlparse(url)
        if (
            candidate.netloc == parsed.netloc
            and candidate.path.rstrip("/") == parsed.path.rstrip("/")
        ):
            return True
    return False


def _bool_value(metadata: Mapping[str, object], key: str) -> bool:
    value = metadata.get(key, False)
    return value if isinstance(value, bool) else False


def _int_value(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key, 0)
    return value if isinstance(value, int) else 0


def _source_canonical_confidence(source_intent_assessment: Mapping[str, object]) -> str:
    value = source_intent_assessment.get("canonical_source_confidence", "none")
    return str(value) if value else "none"


def _candidate_confidence(candidate: Mapping[str, object]) -> str:
    score = _int_value(candidate, "confidence_score")
    if score >= 75:
        return "high"
    if score >= 70:
        return "medium"
    return "low"
