from __future__ import annotations

import ssl
from typing import cast

import pytest
from pytest import MonkeyPatch

from knowledge_adapters.confluence.auth import (
    SUPPORTED_AUTH_METHODS,
    build_request_auth,
    select_auth_strategy,
)


class _FakeSSLContext:
    def __init__(self) -> None:
        self.loaded_cert_chain: tuple[str, str | None] | None = None

    def load_cert_chain(self, *, certfile: str, keyfile: str | None = None) -> None:
        self.loaded_cert_chain = (certfile, keyfile)


def test_confluence_auth_strategy_selection_keeps_stable_names() -> None:
    assert SUPPORTED_AUTH_METHODS == ("bearer-env", "client-cert-env")
    assert select_auth_strategy("bearer-env").name == "bearer-env"
    assert select_auth_strategy("client-cert-env").name == "client-cert-env"


def test_confluence_auth_strategy_selection_rejects_unknown_method() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported Confluence auth method 'oauth'. Use 'bearer-env' or 'client-cert-env'.",
    ):
        select_auth_strategy("oauth")


def test_confluence_bearer_strategy_preserves_header_and_tls_defaults(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", " test-token ")

    request_auth = build_request_auth("bearer-env")

    assert request_auth.headers == {"Authorization": "Bearer test-token"}
    assert request_auth.ssl_context is None


def test_confluence_client_cert_strategy_uses_tls_without_auth_header(
    monkeypatch: MonkeyPatch,
) -> None:
    ssl_context = _FakeSSLContext()
    ssl_context_for_return = cast(ssl.SSLContext, ssl_context)

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        lambda *, cafile=None: ssl_context_for_return,
    )

    request_auth = build_request_auth(
        "client-cert-env",
        client_cert_file="/tmp/confluence-client.crt",
        client_key_file="/tmp/confluence-client.key",
    )

    assert request_auth.headers == {}
    assert request_auth.ssl_context is ssl_context_for_return
    assert ssl_context.loaded_cert_chain == (
        "/tmp/confluence-client.crt",
        "/tmp/confluence-client.key",
    )


def test_confluence_client_cert_strategy_rejects_missing_certificate() -> None:
    with pytest.raises(
        ValueError,
        match="Missing Confluence client certificate",
    ):
        build_request_auth("client-cert-env")


def test_confluence_client_cert_strategy_wraps_invalid_tls_config(
    monkeypatch: MonkeyPatch,
) -> None:
    def fail_create_default_context(*, cafile: str | None = None) -> ssl.SSLContext:
        del cafile
        raise ssl.SSLError("bad tls")

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        fail_create_default_context,
    )

    with pytest.raises(ValueError, match="Invalid Confluence CA bundle"):
        build_request_auth("client-cert-env", client_cert_file="/tmp/confluence-client.pem")
