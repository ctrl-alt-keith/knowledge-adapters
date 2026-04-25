"""Normalization logic for the github_metadata adapter."""

from __future__ import annotations

from collections.abc import Mapping

EMPTY_BODY_MARKER = "(empty issue body)"


def normalize_issue_to_markdown(issue: Mapping[str, object]) -> str:
    """Normalize one issue payload into deterministic markdown."""
    number_value = issue.get("number")
    if not isinstance(number_value, int) or isinstance(number_value, bool):
        raise ValueError("issue number must be an integer.")
    number = number_value
    title = str(issue.get("title", ""))
    state = str(issue.get("state", ""))
    author = issue.get("author")
    author_text = "" if author is None else str(author)
    created_at = str(issue.get("created_at", ""))
    updated_at = str(issue.get("updated_at", ""))
    source_url = str(issue.get("source_url", ""))
    repo = str(issue.get("repo", ""))
    body = str(issue.get("body") or "").rstrip("\n")
    body_text = body if body else EMPTY_BODY_MARKER

    return f"""# Issue #{number}: {title}

## Metadata
- repo: {repo}
- resource_type: issue
- number: {number}
- state: {state}
- author: {author_text}
- created_at: {created_at}
- updated_at: {updated_at}
- source_url: {source_url}

## Body

{body_text}
"""
