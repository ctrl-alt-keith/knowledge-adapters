"""Normalization logic for the github_metadata adapter."""

from __future__ import annotations

from collections.abc import Mapping

EMPTY_BODY_MARKER = "(empty issue body)"
EMPTY_PULL_REQUEST_BODY_MARKER = "(empty pull request body)"
EMPTY_RELEASE_BODY_MARKER = "(empty release body)"
EMPTY_COMMENT_BODY_MARKER = "(empty issue comment body)"
EMPTY_PR_COMMENT_BODY_MARKER = "(empty pull request comment body)"
EMPTY_PR_REVIEW_COMMENT_BODY_MARKER = "(empty pull request review comment body)"


def normalize_issue_to_markdown(issue: Mapping[str, object]) -> str:
    """Normalize one issue payload into deterministic markdown."""
    return _normalize_record_to_markdown(
        issue,
        heading_prefix="Issue",
        resource_type="issue",
        empty_body_marker=EMPTY_BODY_MARKER,
        include_comments=True,
    )


def normalize_pull_request_to_markdown(pull_request: Mapping[str, object]) -> str:
    """Normalize one pull request payload into deterministic markdown."""
    return _normalize_record_to_markdown(
        pull_request,
        heading_prefix="Pull Request",
        resource_type="pull_request",
        empty_body_marker=EMPTY_PULL_REQUEST_BODY_MARKER,
        include_comments=False,
        comments_section=_normalize_pull_request_sections(pull_request),
    )


def normalize_release_to_markdown(release: Mapping[str, object]) -> str:
    """Normalize one release payload into deterministic markdown."""
    release_id_value = release.get("release_id")
    if not isinstance(release_id_value, int) or isinstance(release_id_value, bool):
        raise ValueError("release_id must be an integer.")
    tag_name_value = release.get("tag_name")
    if not isinstance(tag_name_value, str):
        raise ValueError("tag_name must be a string.")
    title_value = release.get("title", "")
    if not isinstance(title_value, str):
        raise ValueError("title must be a string.")
    draft_value = release.get("draft")
    if not isinstance(draft_value, bool):
        raise ValueError("draft must be a boolean.")
    prerelease_value = release.get("prerelease")
    if not isinstance(prerelease_value, bool):
        raise ValueError("prerelease must be a boolean.")

    author = release.get("author")
    author_text = "" if author is None else str(author)
    created_at = str(release.get("created_at", ""))
    published_at = release.get("published_at")
    published_at_text = "" if published_at is None else str(published_at)
    source_url = str(release.get("source_url", ""))
    repo = str(release.get("repo", ""))
    body = str(release.get("body") or "").rstrip("\n")
    body_text = body if body else EMPTY_RELEASE_BODY_MARKER
    heading = (
        f"# Release {tag_name_value}: {title_value}"
        if title_value
        else f"# Release {tag_name_value}"
    )

    return f"""{heading}

## Metadata
- repo: {repo}
- resource_type: release
- release_id: {release_id_value}
- tag_name: {tag_name_value}
- title: {title_value}
- author: {author_text}
- created_at: {created_at}
- published_at: {published_at_text}
- draft: {str(draft_value).lower()}
- prerelease: {str(prerelease_value).lower()}
- source_url: {source_url}

## Body

{body_text}
"""


def _normalize_record_to_markdown(
    record: Mapping[str, object],
    *,
    heading_prefix: str,
    resource_type: str,
    empty_body_marker: str,
    include_comments: bool,
    comments_section: str = "",
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
    rendered_comments_section = (
        _normalize_comments_section(record.get("comments"))
        if include_comments
        else comments_section
    )

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

{body_text}{rendered_comments_section}
"""


def _normalize_comments_section(comments_value: object) -> str:
    if comments_value is None:
        return ""
    if not isinstance(comments_value, (list, tuple)):
        raise ValueError("issue comments must be a list or tuple when provided.")
    if not comments_value:
        return ""

    rendered_comments: list[str] = []
    for index, comment_value in enumerate(comments_value, start=1):
        if not isinstance(comment_value, Mapping):
            raise ValueError("issue comments must contain mapping entries.")
        author = comment_value.get("author")
        author_text = "" if author is None else str(author)
        created_at = str(comment_value.get("created_at", ""))
        updated_at = str(comment_value.get("updated_at", ""))
        body = str(comment_value.get("body") or "").rstrip("\n")
        body_text = body if body else EMPTY_COMMENT_BODY_MARKER
        rendered_comments.append(
            f"""### Comment {index}

- author: {author_text}
- created_at: {created_at}
- updated_at: {updated_at}

{body_text}
"""
        )
    return "\n\n## Comments\n\n" + "\n".join(rendered_comments).rstrip("\n")


def _normalize_pull_request_sections(record: Mapping[str, object]) -> str:
    sections = [
        _normalize_pull_request_comments_section(record.get("comments")),
        _normalize_pull_request_review_comments_section(record.get("review_comments")),
    ]
    return "".join(section for section in sections if section)


def _normalize_pull_request_comments_section(comments_value: object) -> str:
    if comments_value is None:
        return ""
    if not isinstance(comments_value, (list, tuple)):
        raise ValueError("pull request comments must be a list or tuple when provided.")
    if not comments_value:
        return ""

    rendered_comments: list[str] = []
    for index, comment_value in enumerate(comments_value, start=1):
        if not isinstance(comment_value, Mapping):
            raise ValueError("pull request comments must contain mapping entries.")
        author = comment_value.get("author")
        body = str(comment_value.get("body") or "").rstrip("\n")
        rendered_comments.append(
            f"""### Comment {index}

- id: {_format_optional_value(comment_value.get("comment_id"))}
- source_url: {_format_optional_value(comment_value.get("source_url"))}
- author: {'' if author is None else str(author)}
- created_at: {str(comment_value.get("created_at", ""))}
- updated_at: {str(comment_value.get("updated_at", ""))}

{body if body else EMPTY_PR_COMMENT_BODY_MARKER}
"""
        )
    return "\n\n## Comments\n\n" + "\n".join(rendered_comments).rstrip("\n")


def _normalize_pull_request_review_comments_section(comments_value: object) -> str:
    if comments_value is None:
        return ""
    if not isinstance(comments_value, (list, tuple)):
        raise ValueError("pull request review comments must be a list or tuple when provided.")
    if not comments_value:
        return ""

    rendered_comments: list[str] = []
    for index, comment_value in enumerate(comments_value, start=1):
        if not isinstance(comment_value, Mapping):
            raise ValueError("pull request review comments must contain mapping entries.")
        author = comment_value.get("author")
        body = str(comment_value.get("body") or "").rstrip("\n")
        rendered_comments.append(
            f"""### Review Comment {index}

- id: {_format_optional_value(comment_value.get("comment_id"))}
- source_url: {_format_optional_value(comment_value.get("source_url"))}
- author: {'' if author is None else str(author)}
- created_at: {str(comment_value.get("created_at", ""))}
- updated_at: {str(comment_value.get("updated_at", ""))}
- path: {_format_optional_value(comment_value.get("path"))}
- line: {_format_optional_value(comment_value.get("line"))}
- original_line: {_format_optional_value(comment_value.get("original_line"))}
- start_line: {_format_optional_value(comment_value.get("start_line"))}
- original_start_line: {_format_optional_value(comment_value.get("original_start_line"))}
- position: {_format_optional_value(comment_value.get("position"))}
- original_position: {_format_optional_value(comment_value.get("original_position"))}
- side: {_format_optional_value(comment_value.get("side"))}
- start_side: {_format_optional_value(comment_value.get("start_side"))}

{body if body else EMPTY_PR_REVIEW_COMMENT_BODY_MARKER}
"""
        )
    return "\n\n## Review Comments\n\n" + "\n".join(rendered_comments).rstrip("\n")


def _format_optional_value(value: object) -> str:
    return "" if value is None else str(value)
