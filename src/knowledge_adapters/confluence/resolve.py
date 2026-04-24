"""Target resolution for the Confluence adapter."""

from __future__ import annotations

import re
from urllib import parse

from knowledge_adapters.confluence.models import ResolvedTarget

_PAGE_ID_RE = re.compile(r"^\d+$")
_PAGE_ID_IN_PATH_RE = re.compile(r"/pages/(\d+)(?:/|$)")
_SPACE_KEY_RE = re.compile(r"^[^\s/]+$")


def _parse_absolute_http_url(value: str) -> parse.ParseResult | None:
    parsed = parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed


def validate_base_url(base_url: str) -> str:
    """Validate and normalize a CLI-facing Confluence base URL."""
    normalized_base_url = base_url.strip()
    if _parse_absolute_http_url(normalized_base_url) is None:
        raise ValueError(
            f"--base-url {base_url!r} is invalid. "
            "Provide a full http:// or https:// Confluence base URL, "
            "for example 'https://example.com/wiki'."
        )
    return normalized_base_url


def validate_space_key(space_key: str) -> str:
    """Validate and normalize a CLI-facing Confluence space key."""
    normalized_space_key = space_key.strip()
    if not normalized_space_key:
        raise ValueError("--space-key cannot be empty.")
    if _SPACE_KEY_RE.fullmatch(normalized_space_key) is None:
        raise ValueError("--space-key must not contain whitespace or '/'.")
    return normalized_space_key


def space_key_from_url_for_base_url(space_url: str, *, base_url: str) -> str:
    """Extract and validate a Confluence space key from a space overview URL."""
    validated_base_url = validate_base_url(base_url)
    cleaned = space_url.strip()
    parsed_url = _parse_absolute_http_url(cleaned)
    if parsed_url is None:
        raise ValueError(
            f"--space-url {space_url!r} is malformed. "
            "Provide a full Confluence space overview URL."
        )

    if not _url_matches_base_url(page_url=cleaned, base_url=validated_base_url):
        raise ValueError(
            f"--space-url {space_url!r} does not match --base-url {validated_base_url!r}. "
            "Use a URL under that base URL."
        )

    path_parts = [parse.unquote(part) for part in parsed_url.path.strip("/").split("/")]
    for index, part in enumerate(path_parts):
        if part != "spaces":
            continue
        if index + 2 >= len(path_parts):
            break
        space_key = path_parts[index + 1]
        overview = path_parts[index + 2]
        if overview == "overview" and index + 3 == len(path_parts):
            return validate_space_key(space_key)

    raise ValueError(
        f"--space-url {space_url!r} must match /spaces/{{SPACE}}/overview."
    )


def _page_id_from_url(parsed_url: parse.ParseResult) -> str | None:
    query_page_ids = parse.parse_qs(parsed_url.query).get("pageId", [])
    if query_page_ids:
        page_id = query_page_ids[0]
        if _PAGE_ID_RE.fullmatch(page_id):
            return page_id

    path_match = _PAGE_ID_IN_PATH_RE.search(parsed_url.path)
    if path_match:
        return path_match.group(1)

    return None


def _url_matches_base_url(*, page_url: str, base_url: str) -> bool:
    parsed_page_url = _parse_absolute_http_url(page_url)
    parsed_base_url = _parse_absolute_http_url(base_url.strip())
    if parsed_page_url is None or parsed_base_url is None:
        return True

    if (
        parsed_page_url.scheme,
        parsed_page_url.netloc,
    ) != (
        parsed_base_url.scheme,
        parsed_base_url.netloc,
    ):
        return False

    normalized_base_path = parsed_base_url.path.rstrip("/")
    if not normalized_base_path:
        return True

    normalized_target_path = parsed_page_url.path.rstrip("/")
    return normalized_target_path == normalized_base_path or normalized_target_path.startswith(
        f"{normalized_base_path}/"
    )


def _canonical_page_url(*, base_url: str, page_id: str) -> str:
    normalized_base_url = base_url.strip().rstrip("/")
    encoded_page_id = parse.quote(page_id, safe="")
    return f"{normalized_base_url}/pages/viewpage.action?pageId={encoded_page_id}"


def resolve_target(target: str) -> ResolvedTarget:
    """Resolve a user-provided target into a canonical form.

    Supports:
    - numeric page IDs
    - URLs containing a page ID
    """
    cleaned = target.strip()

    if _PAGE_ID_RE.fullmatch(cleaned):
        return ResolvedTarget(
            raw_value=cleaned,
            page_id=cleaned,
            page_url=None,
            input_kind="page_id",
        )

    if not cleaned:
        return ResolvedTarget(
            raw_value=cleaned,
            page_id=None,
            page_url=None,
            input_kind="empty",
        )

    if "://" in cleaned:
        parsed_url = _parse_absolute_http_url(cleaned)
        if parsed_url is None:
            return ResolvedTarget(
                raw_value=cleaned,
                page_id=None,
                page_url=None,
                input_kind="invalid_url",
            )

        return ResolvedTarget(
            raw_value=cleaned,
            page_id=_page_id_from_url(parsed_url),
            page_url=cleaned,
            input_kind="url",
        )

    return ResolvedTarget(
        raw_value=cleaned,
        page_id=None,
        page_url=None,
        input_kind="unknown",
    )


def resolve_target_for_base_url(target: str, *, base_url: str) -> ResolvedTarget:
    """Resolve and validate a target for CLI-facing Confluence usage."""
    validated_base_url = validate_base_url(base_url)
    resolved = resolve_target(target)

    if resolved.input_kind == "page_id":
        return ResolvedTarget(
            raw_value=resolved.raw_value,
            page_id=resolved.page_id,
            page_url=_canonical_page_url(
                base_url=validated_base_url,
                page_id=resolved.page_id or "",
            ),
            input_kind=resolved.input_kind,
        )

    if resolved.input_kind == "empty":
        raise ValueError("--target cannot be empty. Provide a page ID or full Confluence page URL.")

    if resolved.input_kind == "invalid_url":
        raise ValueError(
            f"Target URL {resolved.raw_value!r} is malformed. "
            "Provide a full Confluence page URL or page ID."
        )

    if resolved.input_kind == "url":
        if resolved.page_id is None:
            raise ValueError(
                f"Target URL {resolved.raw_value!r} does not include a Confluence page ID. "
                "Use a page URL containing the page ID or pass the page ID directly."
            )
        if resolved.page_url and not _url_matches_base_url(
            page_url=resolved.page_url,
            base_url=validated_base_url,
        ):
            raise ValueError(
                f"Target URL {resolved.raw_value!r} does not match "
                f"--base-url {validated_base_url!r}. "
                "Use a URL under that base URL or pass the page ID directly."
            )
        return ResolvedTarget(
            raw_value=resolved.raw_value,
            page_id=resolved.page_id,
            page_url=_canonical_page_url(base_url=validated_base_url, page_id=resolved.page_id),
            input_kind=resolved.input_kind,
        )

    raise ValueError(
        f"Could not resolve target {resolved.raw_value!r}. "
        "Provide a numeric page ID or full Confluence page URL."
    )
