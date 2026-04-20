"""HTTP/client layer for the Confluence adapter."""

from __future__ import annotations

import json
from urllib import parse, request
from urllib.error import HTTPError, URLError

from knowledge_adapters.confluence.auth import build_auth_headers
from knowledge_adapters.confluence.models import ResolvedTarget


def fetch_page(target: ResolvedTarget) -> dict[str, object]:
    """Fetch a Confluence page.

    This is a stub for the initial scaffold.
    """
    canonical_id = target.page_id or "unknown"

    return {
        "title": f"stub-page-{canonical_id}",
        "canonical_id": canonical_id,
        "source_url": target.page_url or "",
        "content": f"Stub content for page {canonical_id}.",
    }


def _content_api_url(base_url: str, page_id: str) -> str:
    normalized_base = base_url.rstrip("/")
    encoded_page_id = parse.quote(page_id, safe="")
    return (
        f"{normalized_base}/rest/api/content/{encoded_page_id}"
        "?expand=body.storage,_links"
    )


def _child_page_api_url(base_url: str, page_id: str) -> str:
    normalized_base = base_url.rstrip("/")
    encoded_page_id = parse.quote(page_id, safe="")
    return f"{normalized_base}/rest/api/content/{encoded_page_id}/child/page"


def _require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Response error: missing or invalid {key}.")
    return value


def _storage_content(payload: dict[str, object]) -> str:
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ValueError("Response error: missing content.")
    storage = body.get("storage")
    if not isinstance(storage, dict):
        raise ValueError("Response error: missing content.")
    value = storage.get("value")
    if not isinstance(value, str):
        raise ValueError("Response error: missing content.")
    return value


def _absolute_source_url(payload: dict[str, object]) -> str:
    links = payload.get("_links")
    if not isinstance(links, dict):
        raise ValueError("Response error: missing source_url.")

    webui = links.get("webui")
    if not isinstance(webui, str) or not webui:
        raise ValueError("Response error: missing source_url.")

    parsed_webui = parse.urlparse(webui)
    if parsed_webui.scheme and parsed_webui.netloc:
        return webui

    base = links.get("base")
    if not isinstance(base, str) or not base:
        raise ValueError("Response error: missing source_url.")

    parsed_base = parse.urlparse(base)
    if not parsed_base.scheme or not parsed_base.netloc:
        raise ValueError("Response error: missing source_url.")

    if webui.startswith("/"):
        return f"{base.rstrip('/')}{webui}"
    return f"{base.rstrip('/')}/{webui.lstrip('/')}"


def _map_real_page(payload: dict[str, object], requested_page_id: str) -> dict[str, object]:
    canonical_id = _require_string(payload, "id")
    if canonical_id != requested_page_id:
        raise ValueError("Response error: canonical_id mismatch.")

    title = _require_string(payload, "title")
    content = _storage_content(payload)
    source_url = _absolute_source_url(payload)

    return {
        "canonical_id": canonical_id,
        "title": title,
        "content": content,
        "source_url": source_url,
    }


def _map_child_page_ids(payload: dict[str, object]) -> list[str]:
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("Response error: invalid child-list payload.")

    child_page_ids: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Response error: invalid child-list payload.")
        child_page_id = result.get("id")
        if not isinstance(child_page_id, str) or not child_page_id:
            raise ValueError("Response error: invalid child page ID.")
        child_page_ids.append(child_page_id)

    return child_page_ids


def _request_json(api_url: str, *, auth_method: str) -> dict[str, object]:
    headers = dict(build_auth_headers(auth_method))
    api_request = request.Request(
        api_url,
        headers=headers,
    )

    try:
        with request.urlopen(api_request) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise RuntimeError("Confluence auth failure.") from exc
        if exc.code == 404:
            raise RuntimeError("Confluence page not found.") from exc
        raise RuntimeError(f"Confluence request failed with status {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError("Confluence request failed.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Response error: invalid JSON payload.") from exc

    if not isinstance(raw_payload, dict):
        raise ValueError("Response error: invalid payload shape.")

    return raw_payload


def fetch_real_page(
    target: ResolvedTarget,
    *,
    base_url: str,
    auth_method: str,
) -> dict[str, object]:
    """Fetch one Confluence page through the opt-in real client path."""
    page_id = target.page_id
    if not page_id:
        raise ValueError("Response error: canonical_id mismatch.")

    raw_payload = _request_json(
        _content_api_url(base_url, page_id),
        auth_method=auth_method,
    )
    return _map_real_page(raw_payload, page_id)


def list_real_child_page_ids(
    target: ResolvedTarget,
    *,
    base_url: str,
    auth_method: str,
) -> list[str]:
    """List direct child page IDs for one Confluence page in real mode."""
    page_id = target.page_id
    if not page_id:
        raise ValueError("Response error: invalid child page ID.")

    raw_payload = _request_json(
        _child_page_api_url(base_url, page_id),
        auth_method=auth_method,
    )
    return _map_child_page_ids(raw_payload)
