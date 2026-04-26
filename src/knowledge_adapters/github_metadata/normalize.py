"""Normalization logic for the github_metadata adapter."""

from __future__ import annotations

from collections.abc import Mapping

EMPTY_BODY_MARKER = "(empty issue body)"
EMPTY_PULL_REQUEST_BODY_MARKER = "(empty pull request body)"


def normalize_issue_to_markdown(issue: Mapping[str, object]) -> str:
    """Normalize one issue payload into deterministic markdown."""
    return _normalize_record_to_markdown(
        issue,
        heading_prefix="Issue",
        resource_type="issue",
        empty_body_marker=EMPTY_BODY_MARKER,
    )


def normalize_pull_request_to_markdown(pull_request: Mapping[str, object]) -> str:
    """Normalize one pull request payload into deterministic markdown."""
    return _normalize_record_to_markdown(
        pull_request,
        heading_prefix="Pull Request",
        resource_type="pull_request",
        empty_body_marker=EMPTY_PULL_REQUEST_BODY_MARKER,
    )


def _normalize_record_to_markdown(
    record: Mapping[str, object],
    *,
    heading_prefix: str,
    resource_type: str,
    empty_body_marker: str,
) -> str:
    number_value = record.get("number")
    if not isinstance(number_value, int) or isinstance(number_value, bool):
        raise ValueError(f"{resource_type} number must be an integer.")
    number = number_value
    title = str(record.get("title", ""))
    state = str(record.get("state", ""))
    author = record.get("author")
    author_text = "" if author is None else str(author)
    created_at = str(record.get("created_at", ""))
    updated_at = str(record.get("updated_at", ""))
    source_url = str(record.get("source_url", ""))
    repo = str(record.get("repo", ""))
    body = str(record.get("body") or "").rstrip("\n")
    body_text = body if body else empty_body_marker

    return f"""# {heading_prefix} #{number}: {title}

## Metadata
- repo: {repo}
- resource_type: {resource_type}
- number: {number}
- state: {state}
- author: {author_text}
- created_at: {created_at}
- updated_at: {updated_at}
- source_url: {source_url}

## Body

{body_text}
"""
