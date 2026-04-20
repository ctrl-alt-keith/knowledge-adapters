"""Authentication helpers for the Confluence adapter."""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestAuth:
    """Request auth material for the Confluence real client."""

    headers: dict[str, str]
    ssl_context: ssl.SSLContext | None


def build_request_auth(auth_method: str) -> RequestAuth:
    """Build auth material for a supported auth method."""
    if auth_method == "bearer-env":
        headers = _bearer_env_headers()
    elif auth_method == "client-cert-env":
        headers = {}
    else:
        raise ValueError(f"Unsupported auth method: {auth_method}")

    return RequestAuth(
        headers=headers,
        ssl_context=_client_cert_ssl_context(auth_method),
    )


def _bearer_env_headers() -> dict[str, str]:
    token = os.getenv("CONFLUENCE_BEARER_TOKEN", "").strip()
    if not token:
        raise ValueError("CONFLUENCE_BEARER_TOKEN must be set for --client-mode real.")

    return {"Authorization": f"Bearer {token}"}


def _client_cert_ssl_context(auth_method: str) -> ssl.SSLContext | None:
    cert_file = os.getenv("CONFLUENCE_CLIENT_CERT_FILE", "").strip()
    key_file = os.getenv("CONFLUENCE_CLIENT_KEY_FILE", "").strip()

    if key_file and not cert_file:
        raise ValueError(
            "CONFLUENCE_CLIENT_CERT_FILE must be set when CONFLUENCE_CLIENT_KEY_FILE is set."
        )
    if auth_method == "client-cert-env" and not cert_file:
        raise ValueError(
            "CONFLUENCE_CLIENT_CERT_FILE must be set for --client-mode real "
            "when --auth-method client-cert-env."
        )
    if not cert_file:
        return None

    ssl_context = ssl.create_default_context()
    try:
        ssl_context.load_cert_chain(
            certfile=cert_file,
            keyfile=key_file or None,
        )
    except (OSError, ssl.SSLError, ValueError) as exc:
        raise ValueError("Confluence client certificate configuration is invalid.") from exc

    return ssl_context
