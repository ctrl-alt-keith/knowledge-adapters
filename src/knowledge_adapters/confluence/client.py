"""HTTP/client layer for the Confluence adapter."""

from __future__ import annotations

import json
import os
import socket
import ssl
from urllib import parse, request
from urllib.error import HTTPError, URLError

from knowledge_adapters.confluence.auth import build_request_auth
from knowledge_adapters.confluence.models import ResolvedTarget


class ConfluenceRequestError(RuntimeError):
    """Stable request failure with Confluence-specific debug context."""

    def __init__(
        self,
        message: str,
        *,
        request_url: str,
        auth_method: str,
        underlying_error: str,
    ) -> None:
        super().__init__(message)
        self.request_url = request_url
        self.auth_method = auth_method
        self.underlying_error = underlying_error


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
        "page_version": 1,
        "last_modified": "1970-01-01T00:00:00Z",
    }


def _content_api_url(base_url: str, page_id: str, *, expand: str) -> str:
    normalized_base = base_url.rstrip("/")
    encoded_page_id = parse.quote(page_id, safe="")
    return f"{normalized_base}/rest/api/content/{encoded_page_id}?expand={expand}"


def _child_page_api_url(base_url: str, page_id: str) -> str:
    normalized_base = base_url.rstrip("/")
    encoded_page_id = parse.quote(page_id, safe="")
    return f"{normalized_base}/rest/api/content/{encoded_page_id}/child/page"


def _require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Response error: missing or invalid {key}.")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _source_metadata(payload: dict[str, object]) -> tuple[int | None, str | None]:
    version = payload.get("version")
    if not isinstance(version, dict):
        return None, None

    number = version.get("number")
    page_version = number if isinstance(number, int) and not isinstance(number, bool) else None
    last_modified = _optional_string(version, "when")
    return page_version, last_modified


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
    page_version, last_modified = _source_metadata(payload)

    return {
        "canonical_id": canonical_id,
        "title": title,
        "content": content,
        "source_url": source_url,
        "page_version": page_version,
        "last_modified": last_modified,
    }


def _map_real_page_summary(payload: dict[str, object], requested_page_id: str) -> dict[str, object]:
    canonical_id = _require_string(payload, "id")
    if canonical_id != requested_page_id:
        raise ValueError("Response error: canonical_id mismatch.")

    title = _require_string(payload, "title")
    source_url = _absolute_source_url(payload)
    page_version, last_modified = _source_metadata(payload)

    return {
        "canonical_id": canonical_id,
        "title": title,
        "source_url": source_url,
        "page_version": page_version,
        "last_modified": last_modified,
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


def _sanitize_debug_value(value: str) -> str:
    bearer_token = os.getenv("CONFLUENCE_BEARER_TOKEN", "").strip()
    sanitized = value
    if bearer_token:
        sanitized = sanitized.replace(bearer_token, "[redacted]")
    if "-----BEGIN " in sanitized or "-----END " in sanitized:
        return "[redacted secret material]"
    return sanitized


def _underlying_request_error_message(exc: HTTPError | URLError) -> str:
    if isinstance(exc, HTTPError):
        return _sanitize_debug_value(str(exc))

    return _sanitize_debug_value(str(exc.reason))


def _auth_failure_message(auth_method: str) -> str:
    if auth_method == "client-cert-env":
        return (
            "Confluence auth failed. Check CONFLUENCE_CLIENT_CERT_FILE / "
            "CONFLUENCE_CLIENT_KEY_FILE."
        )
    return "Confluence auth failed. Check CONFLUENCE_BEARER_TOKEN."


def _tls_failure_message(auth_method: str) -> str:
    if auth_method == "client-cert-env":
        return (
            "Confluence TLS/client certificate failed. Check "
            "CONFLUENCE_CLIENT_CERT_FILE / CONFLUENCE_CLIENT_KEY_FILE."
        )
    return "Confluence TLS/certificate failed. Verify --base-url and the server certificate."


def _looks_like_tls_or_cert_error(reason: object) -> bool:
    if isinstance(reason, ssl.SSLError):
        return True

    reason_text = str(reason).lower()
    return any(
        fragment in reason_text
        for fragment in (
            "certificate",
            "cert",
            "ssl",
            "tls",
            "handshake",
            "pem",
            "x509",
        )
    )


def _looks_like_network_error(reason: object) -> bool:
    if isinstance(reason, (ConnectionError, TimeoutError, socket.gaierror, socket.timeout)):
        return True

    reason_text = str(reason).lower()
    return any(
        fragment in reason_text
        for fragment in (
            "connection refused",
            "name or service not known",
            "network is unreachable",
            "no route to host",
            "nodename nor servname provided",
            "temporary failure in name resolution",
            "timed out",
        )
    )


def _request_failure_message(exc: HTTPError | URLError, *, auth_method: str) -> str:
    if isinstance(exc, HTTPError):
        if exc.code in {401, 403}:
            return _auth_failure_message(auth_method)
        if exc.code == 404:
            return "Confluence page not found. Verify --target."
        return f"Confluence request failed (status {exc.code}). Verify --base-url and access."

    reason = exc.reason
    if _looks_like_tls_or_cert_error(reason):
        return _tls_failure_message(auth_method)
    if _looks_like_network_error(reason):
        return "Confluence network request failed. Verify --base-url and network access."
    return "Confluence request failed. Verify --base-url and try again."


def _request_json(api_url: str, *, auth_method: str) -> dict[str, object]:
    request_auth = build_request_auth(auth_method)
    api_request = request.Request(
        api_url,
        headers=dict(request_auth.headers),
    )

    try:
        with request.urlopen(api_request, context=request_auth.ssl_context) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise ConfluenceRequestError(
            _request_failure_message(exc, auth_method=auth_method),
            request_url=api_url,
            auth_method=auth_method,
            underlying_error=_underlying_request_error_message(exc),
        ) from exc
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
        _content_api_url(base_url, page_id, expand="body.storage,_links,version"),
        auth_method=auth_method,
    )
    return _map_real_page(raw_payload, page_id)


def fetch_real_page_summary(
    target: ResolvedTarget,
    *,
    base_url: str,
    auth_method: str,
) -> dict[str, object]:
    """Fetch Confluence page metadata used for incremental sync decisions."""
    page_id = target.page_id
    if not page_id:
        raise ValueError("Response error: canonical_id mismatch.")

    raw_payload = _request_json(
        _content_api_url(base_url, page_id, expand="version,_links"),
        auth_method=auth_method,
    )
    return _map_real_page_summary(raw_payload, page_id)


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
