from __future__ import annotations

import io
import json
import re
import ssl
from email.message import Message
from pathlib import Path
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.confluence.models import ResolvedTarget
from tests.cli_output_assertions import assert_dry_run_summary, assert_write_summary


def _confluence_argv(output_dir: Path, *extra_args: str) -> list[str]:
    return [
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        str(output_dir),
        *extra_args,
    ]


def _load_manifest(output_dir: Path) -> dict[str, object]:
    payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    return cast(dict[str, object], payload)


def _real_target(page_id: str = "12345") -> ResolvedTarget:
    return ResolvedTarget(
        raw_value=page_id,
        page_id=page_id,
        page_url=None,
    )


def _fetch_real_page(
    target: ResolvedTarget,
    *,
    base_url: str = "https://example.com/wiki",
    auth_method: str = "bearer-env",
) -> dict[str, object]:
    from knowledge_adapters.confluence import client as client_module

    client_module_any = cast(Any, client_module)
    page = client_module_any.fetch_real_page(
        target,
        base_url=base_url,
        auth_method=auth_method,
    )
    return cast(dict[str, object], page)


def _list_real_child_page_ids(
    target: ResolvedTarget,
    *,
    base_url: str = "https://example.com/wiki",
    auth_method: str = "bearer-env",
) -> list[str]:
    from knowledge_adapters.confluence import client as client_module

    client_module_any = cast(Any, client_module)
    child_page_ids = client_module_any.list_real_child_page_ids(
        target,
        base_url=base_url,
        auth_method=auth_method,
    )
    return cast(list[str], child_page_ids)


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object], *, status: int = 200) -> None:
        self.status = status
        self._payload = payload

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def getcode(self) -> int:
        return self.status


class _FakeSSLContext:
    def __init__(self) -> None:
        self.loaded_cert_chain: tuple[str, str | None] | None = None

    def load_cert_chain(self, *, certfile: str, keyfile: str | None = None) -> None:
        self.loaded_cert_chain = (certfile, keyfile)


def _valid_confluence_payload(
    *,
    page_id: str = "12345",
) -> dict[str, object]:
    return {
        "id": page_id,
        "title": "Real Page",
        "body": {
            "storage": {
                "value": "<p>Hello from Confluence.</p>",
            }
        },
        "_links": {
            "base": "https://example.com/wiki",
            "webui": f"/spaces/ENG/pages/{page_id}",
        },
        "version": {
            "number": 7,
            "when": "2026-04-20T12:34:56Z",
        },
    }


def _valid_child_list_payload(*, child_page_ids: list[str]) -> dict[str, object]:
    return {
        "results": [
            {
                "id": child_page_id,
            }
            for child_page_id in child_page_ids
        ]
    }


def _http_error(status_code: int) -> HTTPError:
    headers = Message()
    return HTTPError(
        url="https://example.com/wiki/api/content/12345",
        code=status_code,
        msg=f"synthetic http error {status_code}",
        hdrs=headers,
        fp=io.BytesIO(b"{}"),
    )


def _url_error(reason: str | BaseException) -> URLError:
    return URLError(reason)


def test_default_cli_behavior_without_client_mode_still_uses_stub_client(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"

    exit_code = main(_confluence_argv(output_dir))

    assert exit_code == 0

    output_path = output_dir / "pages" / "12345.md"
    assert output_path.read_text(encoding="utf-8") == (
        """# stub-page-12345

## Metadata
- source: confluence
- canonical_id: 12345
- parent_id:
- source_url: https://example.com/wiki/pages/viewpage.action?pageId=12345
- fetched_at:
- updated_at:
- adapter: confluence

## Content

Stub content for page 12345.
"""
    )

    payload = _load_manifest(output_dir)
    assert payload["files"] == [
        {
            "canonical_id": "12345",
            "source_url": "https://example.com/wiki/pages/viewpage.action?pageId=12345",
            "output_path": "pages/12345.md",
            "title": "stub-page-12345",
            "page_version": 1,
            "last_modified": "1970-01-01T00:00:00Z",
        }
    ]


def test_explicit_real_client_mode_selects_real_fetch_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from knowledge_adapters.confluence import client as client_module

    def stub_real_fetch(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "canonical_id": "12345",
            "title": "Real Page",
            "content": "<p>Hello from Confluence.</p>",
            "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
            "page_version": 7,
            "last_modified": "2026-04-20T12:34:56Z",
        }

    def fail_if_stub_used(target: ResolvedTarget) -> dict[str, object]:
        raise AssertionError(f"stub client should not be used in real mode for {target.page_id}")

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(client_module, "fetch_page", fail_if_stub_used)

    output_dir = tmp_path / "out"
    exit_code = main(_confluence_argv(output_dir, "--client-mode", "real"))

    assert exit_code == 0

    output_path = output_dir / "pages" / "12345.md"
    rendered = output_path.read_text(encoding="utf-8")
    assert "# Real Page" in rendered
    assert "<p>Hello from Confluence.</p>" in rendered
    assert "Stub content for page 12345." not in rendered


def test_stub_and_real_single_page_write_runs_share_the_same_cli_shape(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    stub_output_dir = tmp_path / "stub-out"
    stub_exit_code = main(_confluence_argv(stub_output_dir))
    assert stub_exit_code == 0

    stub_output = capsys.readouterr().out
    assert "Confluence adapter invoked" in stub_output
    assert "client_mode: stub" in stub_output
    assert "content_source: scaffolded page content" in stub_output
    assert "fetch_scope: page" in stub_output
    assert "run_mode: write" in stub_output
    assert "Plan: Confluence run" in stub_output
    assert "resolved_page_id: 12345" in stub_output
    assert f"Artifact: {stub_output_dir / 'pages' / '12345.md'}" in stub_output
    assert f"Manifest: {stub_output_dir / 'manifest.json'}" in stub_output
    assert "planned_action: write" in stub_output
    assert "auth_method:" not in stub_output
    assert f"Manifest: {stub_output_dir / 'manifest.json'}" in stub_output
    assert_write_summary(stub_output, wrote=1, skipped=0)

    def stub_real_fetch(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "canonical_id": "12345",
            "title": "Real Page",
            "content": "<p>Hello from Confluence.</p>",
            "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
            "page_version": 7,
            "last_modified": "2026-04-20T12:34:56Z",
        }

    def fail_if_stub_used(target: ResolvedTarget) -> dict[str, object]:
        raise AssertionError(f"stub client should not be used in real mode for {target.page_id}")

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(client_module, "fetch_page", fail_if_stub_used)

    real_output_dir = tmp_path / "real-out"
    real_exit_code = main(_confluence_argv(real_output_dir, "--client-mode", "real"))
    assert real_exit_code == 0

    real_output = capsys.readouterr().out
    assert "Confluence adapter invoked" in real_output
    assert "client_mode: real" in real_output
    assert "content_source: live Confluence content" in real_output
    assert "fetch_scope: page" in real_output
    assert "run_mode: write" in real_output
    assert "Plan: Confluence run" in real_output
    assert "resolved_page_id: 12345" in real_output
    assert f"Artifact: {real_output_dir / 'pages' / '12345.md'}" in real_output
    assert f"Manifest: {real_output_dir / 'manifest.json'}" in real_output
    assert "planned_action: write" in real_output
    assert "auth_method: bearer-env" in real_output
    assert f"Manifest: {real_output_dir / 'manifest.json'}" in real_output
    assert_write_summary(real_output, wrote=1, skipped=0)


def test_stub_and_real_single_page_dry_runs_share_the_same_plan_shape(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from knowledge_adapters.confluence import client as client_module

    stub_output_dir = tmp_path / "stub-out"
    stub_exit_code = main(_confluence_argv(stub_output_dir, "--dry-run"))
    assert stub_exit_code == 0

    stub_output = capsys.readouterr().out
    assert "client_mode: stub" in stub_output
    assert "content_source: scaffolded page content" in stub_output
    assert "mode: single" in stub_output
    assert "run_mode: dry-run" in stub_output
    assert "Plan: Confluence run" in stub_output
    assert "resolved_page_id: 12345" in stub_output
    assert "source_url: https://example.com/wiki/pages/viewpage.action?pageId=12345" in stub_output
    assert f"Artifact: {stub_output_dir / 'pages' / '12345.md'}" in stub_output
    assert f"Manifest: {stub_output_dir / 'manifest.json'}" in stub_output
    assert "planned_action: would write" in stub_output
    assert_dry_run_summary(stub_output, would_write=1, would_skip=0)

    def stub_real_fetch(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "canonical_id": "12345",
            "title": "Real Page",
            "content": "<p>Hello from Confluence.</p>",
            "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
            "page_version": 7,
            "last_modified": "2026-04-20T12:34:56Z",
        }

    def fail_if_stub_used(target: ResolvedTarget) -> dict[str, object]:
        raise AssertionError(f"stub client should not be used in real mode for {target.page_id}")

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    monkeypatch.setattr(client_module, "fetch_page", fail_if_stub_used)

    real_output_dir = tmp_path / "real-out"
    real_exit_code = main(_confluence_argv(real_output_dir, "--client-mode", "real", "--dry-run"))
    assert real_exit_code == 0

    real_output = capsys.readouterr().out
    assert "client_mode: real" in real_output
    assert "content_source: live Confluence content" in real_output
    assert "mode: single" in real_output
    assert "run_mode: dry-run" in real_output
    assert "auth_method: bearer-env" in real_output
    assert "Plan: Confluence run" in real_output
    assert "resolved_page_id: 12345" in real_output
    assert "source_url: https://example.com/wiki/spaces/ENG/pages/12345" in real_output
    assert f"Artifact: {real_output_dir / 'pages' / '12345.md'}" in real_output
    assert f"Manifest: {real_output_dir / 'manifest.json'}" in real_output
    assert "planned_action: would write" in real_output
    assert_dry_run_summary(real_output, would_write=1, would_skip=0)


@pytest.mark.parametrize(
    "token_value",
    [
        None,
        "",
    ],
)
def test_real_fetch_requires_nonempty_bearer_token_before_request(
    monkeypatch: MonkeyPatch,
    token_value: str | None,
) -> None:
    request_count = 0

    def fail_if_requested(*args: object, **kwargs: object) -> object:
        nonlocal request_count
        request_count += 1
        raise AssertionError("network request should not be attempted without auth")

    if token_value is None:
        monkeypatch.delenv("CONFLUENCE_BEARER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", token_value)

    monkeypatch.setattr("urllib.request.urlopen", fail_if_requested)

    with pytest.raises(
        ValueError,
        match=(
            "Missing Confluence bearer token\\. Set CONFLUENCE_BEARER_TOKEN for "
            "--client-mode real --auth-method bearer-env\\."
        ),
    ):
        _fetch_real_page(_real_target())

    assert request_count == 0


def test_real_fetch_maps_valid_confluence_response_into_adapter_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(_valid_confluence_payload()),
    )

    page = _fetch_real_page(_real_target())

    assert page == {
        "canonical_id": "12345",
        "title": "Real Page",
        "content": "<p>Hello from Confluence.</p>",
        "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
        "page_version": 7,
        "last_modified": "2026-04-20T12:34:56Z",
    }
    assert str(page["source_url"]).startswith("https://")


def test_real_fetch_passes_no_client_cert_context_by_default(
    monkeypatch: MonkeyPatch,
) -> None:
    observed_contexts: list[object | None] = []

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        del args
        observed_contexts.append(kwargs.get("context"))
        return _FakeHTTPResponse(_valid_confluence_payload())

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.delenv("CONFLUENCE_CLIENT_CERT_FILE", raising=False)
    monkeypatch.delenv("CONFLUENCE_CLIENT_KEY_FILE", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page = _fetch_real_page(_real_target())

    assert page["canonical_id"] == "12345"
    assert observed_contexts == [None]


def test_real_fetch_uses_combined_client_cert_pem_when_configured(
    monkeypatch: MonkeyPatch,
) -> None:
    ssl_context = _FakeSSLContext()
    observed_contexts: list[object | None] = []
    observed_request_headers: list[dict[str, str]] = []

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        request_obj = cast(Any, args[0])
        observed_request_headers.append(dict(request_obj.headers))
        observed_contexts.append(kwargs.get("context"))
        return _FakeHTTPResponse(_valid_confluence_payload())

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        lambda: ssl_context,
    )
    monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "/tmp/confluence-client.pem")
    monkeypatch.delenv("CONFLUENCE_CLIENT_KEY_FILE", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page = _fetch_real_page(_real_target(), auth_method="client-cert-env")

    assert page["canonical_id"] == "12345"
    assert ssl_context.loaded_cert_chain == ("/tmp/confluence-client.pem", None)
    assert observed_contexts == [ssl_context]
    assert observed_request_headers == [{}]


def test_real_fetch_uses_split_client_cert_and_key_for_client_cert_auth(
    monkeypatch: MonkeyPatch,
) -> None:
    ssl_context = _FakeSSLContext()
    observed_contexts: list[object | None] = []
    observed_request_headers: list[dict[str, str]] = []

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        request_obj = cast(Any, args[0])
        observed_request_headers.append(dict(request_obj.headers))
        observed_contexts.append(kwargs.get("context"))
        return _FakeHTTPResponse(_valid_confluence_payload())

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        lambda: ssl_context,
    )
    monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "/tmp/confluence-client.crt")
    monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "/tmp/confluence-client.key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page = _fetch_real_page(_real_target(), auth_method="client-cert-env")

    assert page["canonical_id"] == "12345"
    assert ssl_context.loaded_cert_chain == (
        "/tmp/confluence-client.crt",
        "/tmp/confluence-client.key",
    )
    assert observed_contexts == [ssl_context]
    assert observed_request_headers == [{}]


def test_real_fetch_uses_split_client_cert_and_key_with_bearer_auth(
    monkeypatch: MonkeyPatch,
) -> None:
    ssl_context = _FakeSSLContext()
    observed_contexts: list[object | None] = []
    observed_request_headers: list[dict[str, str]] = []

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        request_obj = cast(Any, args[0])
        observed_request_headers.append(dict(request_obj.headers))
        observed_contexts.append(kwargs.get("context"))
        return _FakeHTTPResponse(_valid_confluence_payload())

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        lambda: ssl_context,
    )
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "/tmp/confluence-client.crt")
    monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "/tmp/confluence-client.key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page = _fetch_real_page(_real_target())

    assert page["canonical_id"] == "12345"
    assert ssl_context.loaded_cert_chain == (
        "/tmp/confluence-client.crt",
        "/tmp/confluence-client.key",
    )
    assert observed_contexts == [ssl_context]
    assert observed_request_headers == [{"Authorization": "Bearer test-token"}]


def test_real_fetch_treats_empty_client_key_env_as_omitted_for_combined_pem(
    monkeypatch: MonkeyPatch,
) -> None:
    ssl_context = _FakeSSLContext()
    observed_contexts: list[object | None] = []

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        del args
        observed_contexts.append(kwargs.get("context"))
        return _FakeHTTPResponse(_valid_confluence_payload())

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        lambda: ssl_context,
    )
    monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", " /tmp/confluence-client.pem ")
    monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "   ")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page = _fetch_real_page(_real_target(), auth_method="client-cert-env")

    assert page["canonical_id"] == "12345"
    assert ssl_context.loaded_cert_chain == ("/tmp/confluence-client.pem", None)
    assert observed_contexts == [ssl_context]


def test_real_fetch_ignores_empty_optional_client_cert_env_for_bearer_auth(
    monkeypatch: MonkeyPatch,
) -> None:
    observed_contexts: list[object | None] = []

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        del args
        observed_contexts.append(kwargs.get("context"))
        return _FakeHTTPResponse(_valid_confluence_payload())

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "   ")
    monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "   ")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page = _fetch_real_page(_real_target())

    assert page["canonical_id"] == "12345"
    assert observed_contexts == [None]


def test_real_child_list_maps_valid_confluence_response_into_child_page_ids(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            _valid_child_list_payload(child_page_ids=["200", "300", "300"])
        ),
    )

    child_page_ids = _list_real_child_page_ids(_real_target())

    assert child_page_ids == ["200", "300", "300"]


def test_real_child_list_ignores_extra_irrelevant_fields_in_valid_response(
    monkeypatch: MonkeyPatch,
) -> None:
    payload: dict[str, object] = {
        "results": [
            {
                "id": "200",
                "title": "Child A",
                "status": "current",
            },
            {
                "id": "300",
                "_links": {"webui": "/spaces/ENG/pages/300"},
                "ignored": ["extra", "fields"],
            },
        ]
    }

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(payload),
    )

    child_page_ids = _list_real_child_page_ids(_real_target())

    assert child_page_ids == ["200", "300"]


@pytest.mark.parametrize(
    ("base_url", "webui", "expected_source_url"),
    [
        (
            "https://example.com/wiki",
            "/spaces/ENG/pages/12345",
            "https://example.com/wiki/spaces/ENG/pages/12345",
        ),
        (
            "https://example.com/wiki/",
            "/spaces/ENG/pages/12345",
            "https://example.com/wiki/spaces/ENG/pages/12345",
        ),
        (
            "https://example.com/wiki/",
            "spaces/ENG/pages/12345",
            "https://example.com/wiki/spaces/ENG/pages/12345",
        ),
        (
            "https://other.example.test/root",
            "https://example.com/wiki/spaces/ENG/pages/12345",
            "https://example.com/wiki/spaces/ENG/pages/12345",
        ),
    ],
)
def test_real_fetch_constructs_absolute_source_url_for_link_variations(
    monkeypatch: MonkeyPatch,
    base_url: str,
    webui: str,
    expected_source_url: str,
) -> None:
    payload = _valid_confluence_payload()
    payload["_links"] = {
        "base": base_url,
        "webui": webui,
    }

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(payload),
    )

    page = _fetch_real_page(_real_target())

    assert page["source_url"] == expected_source_url


def test_real_fetch_ignores_extra_irrelevant_fields_in_valid_response(
    monkeypatch: MonkeyPatch,
) -> None:
    payload = _valid_confluence_payload()
    payload["version"] = {"number": 7, "when": "2026-04-20T12:34:56Z"}
    payload["space"] = {"key": "ENG"}
    payload["ignored"] = ["extra", "fields"]

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(payload),
    )

    page = _fetch_real_page(_real_target())

    assert page == {
        "canonical_id": "12345",
        "title": "Real Page",
        "content": "<p>Hello from Confluence.</p>",
        "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
        "page_version": 7,
        "last_modified": "2026-04-20T12:34:56Z",
    }


@pytest.mark.parametrize(
    ("status_code", "auth_method", "expected_message"),
    [
        (
            401,
            "bearer-env",
            "Confluence auth failed. Check CONFLUENCE_BEARER_TOKEN.",
        ),
        (
            403,
            "bearer-env",
            "Confluence auth failed. Check CONFLUENCE_BEARER_TOKEN.",
        ),
        (
            403,
            "client-cert-env",
            "Confluence auth failed. Check CONFLUENCE_CLIENT_CERT_FILE / "
            "CONFLUENCE_CLIENT_KEY_FILE.",
        ),
        (404, "bearer-env", "Confluence page not found. Verify --target."),
    ],
)
def test_real_fetch_maps_http_status_failures(
    monkeypatch: MonkeyPatch,
    status_code: int,
    auth_method: str,
    expected_message: str,
) -> None:
    def raise_http_error(*args: object, **kwargs: object) -> object:
        raise _http_error(status_code)

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    if auth_method == "client-cert-env":
        monkeypatch.setattr(
            "knowledge_adapters.confluence.auth.ssl.create_default_context",
            lambda: _FakeSSLContext(),
        )
        monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "/tmp/confluence-client.crt")
        monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "/tmp/confluence-client.key")
    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)

    with pytest.raises(RuntimeError, match=f"^{re.escape(expected_message)}$"):
        _fetch_real_page(_real_target(), auth_method=auth_method)


@pytest.mark.parametrize(
    ("raised_error", "auth_method", "expected_message"),
    [
        (
            _url_error(ssl.SSLError("tlsv13 alert certificate required")),
            "client-cert-env",
            "Confluence TLS/client certificate failed. Check "
            "CONFLUENCE_CLIENT_CERT_FILE / CONFLUENCE_CLIENT_KEY_FILE.",
        ),
        (
            _url_error(TimeoutError("timed out")),
            "bearer-env",
            "Confluence network request failed. Verify --base-url and network access.",
        ),
        (
            _url_error(ValueError("synthetic transport failure")),
            "bearer-env",
            "Confluence request failed. Verify --base-url and try again.",
        ),
    ],
)
def test_real_fetch_maps_url_failures_to_clear_categories(
    monkeypatch: MonkeyPatch,
    raised_error: URLError,
    auth_method: str,
    expected_message: str,
) -> None:
    def raise_url_error(*args: object, **kwargs: object) -> object:
        raise raised_error

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    if auth_method == "client-cert-env":
        monkeypatch.setattr(
            "knowledge_adapters.confluence.auth.ssl.create_default_context",
            lambda: _FakeSSLContext(),
        )
        monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "/tmp/confluence-client.crt")
        monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "/tmp/confluence-client.key")
    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    with pytest.raises(RuntimeError, match=f"^{re.escape(expected_message)}$"):
        _fetch_real_page(_real_target(), auth_method=auth_method)


def test_real_fetch_requires_client_cert_file_for_client_cert_auth_before_request(
    monkeypatch: MonkeyPatch,
) -> None:
    request_count = 0

    def fail_if_requested(*args: object, **kwargs: object) -> object:
        nonlocal request_count
        del args, kwargs
        request_count += 1
        raise AssertionError("network request should not be attempted without client cert")

    monkeypatch.delenv("CONFLUENCE_CLIENT_CERT_FILE", raising=False)
    monkeypatch.delenv("CONFLUENCE_CLIENT_KEY_FILE", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fail_if_requested)

    with pytest.raises(
        ValueError,
        match=(
            "Missing Confluence client certificate\\. Set "
            "CONFLUENCE_CLIENT_CERT_FILE for --client-mode real --auth-method "
            "client-cert-env\\."
        ),
    ):
        _fetch_real_page(_real_target(), auth_method="client-cert-env")

    assert request_count == 0


def test_real_fetch_rejects_client_key_without_cert_before_request(
    monkeypatch: MonkeyPatch,
) -> None:
    request_count = 0

    def fail_if_requested(*args: object, **kwargs: object) -> object:
        nonlocal request_count
        del args, kwargs
        request_count += 1
        raise AssertionError("network request should not be attempted with invalid cert config")

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.delenv("CONFLUENCE_CLIENT_CERT_FILE", raising=False)
    monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "/tmp/confluence-client.key")
    monkeypatch.setattr("urllib.request.urlopen", fail_if_requested)

    with pytest.raises(
        ValueError,
        match=(
            "Incomplete Confluence client certificate config\\. Set "
            "CONFLUENCE_CLIENT_CERT_FILE, and set CONFLUENCE_CLIENT_KEY_FILE only "
            "when the key is in a separate file\\."
        ),
    ):
        _fetch_real_page(_real_target())

    assert request_count == 0


def test_real_fetch_treats_empty_client_cert_env_as_missing_for_client_cert_auth(
    monkeypatch: MonkeyPatch,
) -> None:
    request_count = 0

    def fail_if_requested(*args: object, **kwargs: object) -> object:
        nonlocal request_count
        del args, kwargs
        request_count += 1
        raise AssertionError("network request should not be attempted without client cert")

    monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "   ")
    monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "   ")
    monkeypatch.setattr("urllib.request.urlopen", fail_if_requested)

    with pytest.raises(
        ValueError,
        match=(
            "Missing Confluence client certificate\\. Set "
            "CONFLUENCE_CLIENT_CERT_FILE for --client-mode real --auth-method "
            "client-cert-env\\."
        ),
    ):
        _fetch_real_page(_real_target(), auth_method="client-cert-env")

    assert request_count == 0


def test_real_fetch_surfaces_clear_invalid_client_cert_configuration(
    monkeypatch: MonkeyPatch,
) -> None:
    request_count = 0

    class _BrokenSSLContext:
        def load_cert_chain(self, *, certfile: str, keyfile: str | None = None) -> None:
            del certfile, keyfile
            raise OSError("synthetic cert load failure")

    def fail_if_requested(*args: object, **kwargs: object) -> object:
        nonlocal request_count
        del args, kwargs
        request_count += 1
        raise AssertionError("network request should not be attempted with invalid certs")

    monkeypatch.setattr(
        "knowledge_adapters.confluence.auth.ssl.create_default_context",
        lambda: _BrokenSSLContext(),
    )
    monkeypatch.setenv("CONFLUENCE_CLIENT_CERT_FILE", "/tmp/confluence-client.crt")
    monkeypatch.setenv("CONFLUENCE_CLIENT_KEY_FILE", "/tmp/confluence-client.key")
    monkeypatch.setattr("urllib.request.urlopen", fail_if_requested)

    with pytest.raises(
        ValueError,
        match=(
            "Invalid Confluence client certificate configuration\\. "
            "Check CONFLUENCE_CLIENT_CERT_FILE and optional "
            "CONFLUENCE_CLIENT_KEY_FILE\\."
        ),
    ):
        _fetch_real_page(_real_target(), auth_method="client-cert-env")

    assert request_count == 0


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        (
            {
                "id": "12345",
                "title": "Real Page",
                "_links": {
                    "base": "https://example.com/wiki",
                    "webui": "/spaces/ENG/pages/12345",
                },
            },
            "content",
        ),
        (
            {
                "id": "",
                "title": "Real Page",
                "body": {
                    "storage": {
                        "value": "<p>Hello from Confluence.</p>",
                    }
                },
                "_links": {
                    "base": "https://example.com/wiki",
                    "webui": "/spaces/ENG/pages/12345",
                },
            },
            "id",
        ),
        (
            {
                "id": "12345",
                "title": "",
                "body": {
                    "storage": {
                        "value": "<p>Hello from Confluence.</p>",
                    }
                },
                "_links": {
                    "base": "https://example.com/wiki",
                    "webui": "/spaces/ENG/pages/12345",
                },
            },
            "title",
        ),
        (
            {
                "id": "12345",
                "title": "Real Page",
                "body": {
                    "storage": {
                        "value": 123,
                    }
                },
                "_links": {
                    "base": "https://example.com/wiki",
                    "webui": "/spaces/ENG/pages/12345",
                },
            },
            "content",
        ),
        (
            {
                "id": "12345",
                "title": "Real Page",
                "body": {
                    "storage": {
                        "value": "<p>Hello from Confluence.</p>",
                    }
                },
                "_links": {},
            },
            "source_url",
        ),
        (
            {
                "id": "12345",
                "title": "Real Page",
                "body": {
                    "storage": {
                        "value": "<p>Hello from Confluence.</p>",
                    }
                },
                "_links": {
                    "base": "example.com/wiki",
                    "webui": "/spaces/ENG/pages/12345",
                },
            },
            "source_url",
        ),
        (
            {
                "id": "12345",
                "title": "Real Page",
                "body": {
                    "storage": {
                        "value": "<p>Hello from Confluence.</p>",
                    }
                },
                "_links": {
                    "base": "https://example.com/wiki",
                    "webui": "",
                },
            },
            "source_url",
        ),
        (
            {
                "id": "12345",
                "title": "Real Page",
                "body": {
                    "storage": {
                        "value": "<p>Hello from Confluence.</p>",
                    }
                },
                "_links": {
                    "base": "https://example.com/wiki",
                    "webui": 123,
                },
            },
            "source_url",
        ),
        (
            _valid_confluence_payload(page_id="99999"),
            "canonical_id",
        ),
    ],
)
def test_real_fetch_fails_fast_on_invalid_response_shapes(
    monkeypatch: MonkeyPatch,
    payload: dict[str, object],
    expected_fragment: str,
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(payload),
    )

    with pytest.raises(ValueError, match=expected_fragment):
        _fetch_real_page(_real_target())


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        ({}, "child-list payload"),
        ({"results": [123]}, "child-list payload"),
        ({"results": [{"id": "200"}, {}]}, "child page ID"),
        ({"results": [{"id": "200"}, {"id": 300}]}, "child page ID"),
        ({"results": [{"id": ""}]}, "child page ID"),
        ({"results": [{"id": None}]}, "child page ID"),
    ],
)
def test_real_child_list_fails_fast_on_invalid_response_shapes(
    monkeypatch: MonkeyPatch,
    payload: dict[str, object],
    expected_fragment: str,
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(payload),
    )

    with pytest.raises(ValueError, match=expected_fragment):
        _list_real_child_page_ids(_real_target())


@pytest.mark.parametrize(
    ("raised_error", "expected_message"),
    [
        (
            RuntimeError("Confluence auth failed. Check CONFLUENCE_BEARER_TOKEN."),
            "Confluence auth failed. Check CONFLUENCE_BEARER_TOKEN.",
        ),
        (
            RuntimeError(
                "Confluence TLS/client certificate failed. Check "
                "CONFLUENCE_CLIENT_CERT_FILE / CONFLUENCE_CLIENT_KEY_FILE."
            ),
            "Confluence TLS/client certificate failed. Check "
            "CONFLUENCE_CLIENT_CERT_FILE / CONFLUENCE_CLIENT_KEY_FILE.",
        ),
        (
            RuntimeError("Confluence page not found. Verify --target."),
            "Confluence page not found. Verify --target.",
        ),
        (ValueError("Response error: missing source_url."), "Response error: missing source_url."),
    ],
)
def test_real_client_cli_surfaces_fetch_failures_as_concise_cli_errors(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    raised_error: Exception,
    expected_message: str,
) -> None:
    from knowledge_adapters.confluence import client as client_module

    def raise_fetch_error(*args: object, **kwargs: object) -> dict[str, object]:
        raise raised_error

    monkeypatch.setattr(client_module, "fetch_real_page", raise_fetch_error, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main(_confluence_argv(tmp_path / "out", "--client-mode", "real"))

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert captured.err == f"knowledge-adapters confluence: error: {expected_message}\n"
    assert not (tmp_path / "out" / "manifest.json").exists()
    assert not (tmp_path / "out" / "pages" / "12345.md").exists()


def test_real_client_cli_debug_mode_surfaces_request_context_for_request_failures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")

    def raise_url_error(*args: object, **kwargs: object) -> object:
        raise _url_error(ValueError("synthetic transport failure"))

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    with pytest.raises(SystemExit) as exc_info:
        main(_confluence_argv(tmp_path / "out", "--client-mode", "real", "--debug"))

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        captured.err
        == "knowledge-adapters confluence: error: Confluence request failed. "
        "Verify --base-url and try again.\n"
        "  debug request_url: https://example.com/wiki/rest/api/content/12345"
        "?expand=body.storage,_links,version\n"
        "  debug client_mode: real\n"
        "  debug auth_method: bearer-env\n"
        "  debug exception: synthetic transport failure\n"
    )
    assert not (tmp_path / "out" / "manifest.json").exists()
    assert not (tmp_path / "out" / "pages" / "12345.md").exists()


def test_real_client_cli_default_mode_hides_debug_request_context(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")

    def raise_url_error(*args: object, **kwargs: object) -> object:
        raise _url_error(ValueError("synthetic transport failure"))

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    with pytest.raises(SystemExit) as exc_info:
        main(_confluence_argv(tmp_path / "out", "--client-mode", "real"))

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert (
        captured.err
        == "knowledge-adapters confluence: error: Confluence request failed. "
        "Verify --base-url and try again.\n"
    )
    assert "synthetic transport failure" not in captured.err
    assert "rest/api/content/12345" not in captured.err
