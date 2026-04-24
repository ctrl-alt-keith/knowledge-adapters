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


@dataclass(frozen=True)
class ResolvedTLSInputs:
    """Effective TLS/client-certificate inputs after env fallback resolution."""

    ca_bundle: str | None
    client_cert_file: str | None
    client_key_file: str | None


def build_request_auth(
    auth_method: str,
    *,
    ca_bundle: str | None = None,
    client_cert_file: str | None = None,
    client_key_file: str | None = None,
) -> RequestAuth:
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
        ssl_context=_client_cert_ssl_context(
            auth_method,
            ca_bundle=ca_bundle,
            client_cert_file=client_cert_file,
            client_key_file=client_key_file,
        ),
    )


def resolve_tls_inputs(
    *,
    ca_bundle: str | None = None,
    client_cert_file: str | None = None,
    client_key_file: str | None = None,
) -> ResolvedTLSInputs:
    """Resolve the effective TLS/client-certificate file inputs."""
    return ResolvedTLSInputs(
        ca_bundle=_first_non_empty(
            ca_bundle,
            os.getenv("REQUESTS_CA_BUNDLE"),
            os.getenv("SSL_CERT_FILE"),
        ),
        client_cert_file=_first_non_empty(
            client_cert_file,
            os.getenv("CONFLUENCE_CLIENT_CERT_FILE"),
        ),
        client_key_file=_first_non_empty(
            client_key_file,
            os.getenv("CONFLUENCE_CLIENT_KEY_FILE"),
        ),
    )


def _bearer_env_headers() -> dict[str, str]:
    token = os.getenv("CONFLUENCE_BEARER_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "Missing Confluence bearer token. Set CONFLUENCE_BEARER_TOKEN for "
            "--client-mode real --auth-method bearer-env."
        )

    return {"Authorization": f"Bearer {token}"}


def _client_cert_ssl_context(
    auth_method: str,
    *,
    ca_bundle: str | None = None,
    client_cert_file: str | None = None,
    client_key_file: str | None = None,
) -> ssl.SSLContext | None:
    resolved_tls_inputs = resolve_tls_inputs(
        ca_bundle=ca_bundle,
        client_cert_file=client_cert_file,
        client_key_file=client_key_file,
    )
    cert_file = resolved_tls_inputs.client_cert_file
    key_file = resolved_tls_inputs.client_key_file
    resolved_ca_bundle = resolved_tls_inputs.ca_bundle

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
    if not cert_file and not resolved_ca_bundle:
        return None

    try:
        ssl_context = ssl.create_default_context(cafile=resolved_ca_bundle)
    except (OSError, ssl.SSLError, ValueError) as exc:
        raise ValueError("Invalid Confluence CA bundle. Check --ca-bundle.") from exc

    if not cert_file:
        return ssl_context

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


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        normalized_value = value.strip()
        if normalized_value:
            return normalized_value
    return None
