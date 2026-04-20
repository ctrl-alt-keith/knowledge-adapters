"""Authentication helpers for the Confluence adapter."""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass

SUPPORTED_AUTH_METHODS = ("bearer-env", "client-cert-env")


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
        supported_values = " or ".join(repr(method) for method in SUPPORTED_AUTH_METHODS)
        raise ValueError(
            f"Unsupported Confluence auth method {auth_method!r}. Use {supported_values}."
        )

    return RequestAuth(
        headers=headers,
        ssl_context=_client_cert_ssl_context(auth_method),
    )


def _bearer_env_headers() -> dict[str, str]:
    token = os.getenv("CONFLUENCE_BEARER_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "Missing Confluence bearer token. Set CONFLUENCE_BEARER_TOKEN for "
            "--client-mode real --auth-method bearer-env."
        )

    return {"Authorization": f"Bearer {token}"}


def _client_cert_ssl_context(auth_method: str) -> ssl.SSLContext | None:
    cert_file = os.getenv("CONFLUENCE_CLIENT_CERT_FILE", "").strip()
    key_file = os.getenv("CONFLUENCE_CLIENT_KEY_FILE", "").strip()

    if key_file and not cert_file:
        raise ValueError(
            "Incomplete Confluence client certificate config. Set "
            "CONFLUENCE_CLIENT_CERT_FILE, and set CONFLUENCE_CLIENT_KEY_FILE only "
            "when the key is in a separate file."
        )
    if auth_method == "client-cert-env" and not cert_file:
        raise ValueError(
            "Missing Confluence client certificate. Set "
            "CONFLUENCE_CLIENT_CERT_FILE for --client-mode real --auth-method "
            "client-cert-env."
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
        raise ValueError(
            "Invalid Confluence client certificate configuration. "
            "Check CONFLUENCE_CLIENT_CERT_FILE and optional "
            "CONFLUENCE_CLIENT_KEY_FILE."
        ) from exc

    return ssl_context
