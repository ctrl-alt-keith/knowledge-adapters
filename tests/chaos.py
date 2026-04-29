"""Deterministic chaos helpers for adapter tests.

These helpers are test/dev-only seams for exercising adapter failure behavior
without real services, credentials, sleeps, or external network calls. Prefer
installing a named scenario in an adapter test over hand-rolling one-off HTTP
stubs so failure coverage stays readable and repeatable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from email.message import Message
from enum import StrEnum
from types import TracebackType
from typing import Literal, Self
from urllib.error import HTTPError, URLError
from urllib.request import Request

from pytest import MonkeyPatch


class AdapterChaosScenario(StrEnum):
    """Named deterministic adapter failure scenarios."""

    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    INVALID_JSON = "invalid_json"
    EMPTY_RESPONSE = "empty_response"
    PARTIAL_PAYLOAD = "partial_payload"


@dataclass(frozen=True)
class ChaosHTTPResponse:
    """Small urllib-compatible response for deterministic chaos tests."""

    body: bytes
    status: int = 200

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc, tb
        return False

    def read(self) -> bytes:
        return self.body

    def getcode(self) -> int:
        return self.status


@dataclass(frozen=True)
class ConfluenceHTTPChaos:
    """Install named chaos responses at the Confluence real-client HTTP seam."""

    scenario: AdapterChaosScenario
    page_id: str = "12345"
    base_url: str = "https://example.com/wiki"
    bearer_token: str = "chaos-test-token"

    def install(self, monkeypatch: MonkeyPatch) -> None:
        """Patch urllib and auth inputs for a deterministic Confluence test."""
        monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", self.bearer_token)
        monkeypatch.setattr("urllib.request.urlopen", self.urlopen)

    def urlopen(self, request: object, *args: object, **kwargs: object) -> ChaosHTTPResponse:
        """Return or raise the configured scenario as urllib.urlopen would."""
        del args, kwargs

        request_url = _request_url(request)
        if self.scenario == AdapterChaosScenario.TIMEOUT:
            raise URLError(TimeoutError("timed out"))
        if self.scenario == AdapterChaosScenario.RATE_LIMIT:
            headers = Message()
            headers["Retry-After"] = "60"
            raise HTTPError(
                request_url,
                429,
                "Too Many Requests",
                headers,
                None,
            )
        if self.scenario == AdapterChaosScenario.INVALID_JSON:
            return ChaosHTTPResponse(b'{"id": ')
        if self.scenario == AdapterChaosScenario.EMPTY_RESPONSE:
            return ChaosHTTPResponse(b"")
        if self.scenario == AdapterChaosScenario.PARTIAL_PAYLOAD:
            return ChaosHTTPResponse(json.dumps(_partial_page_payload(self)).encode("utf-8"))

        raise AssertionError(f"Unhandled chaos scenario: {self.scenario}")


def install_confluence_http_chaos(
    monkeypatch: MonkeyPatch,
    scenario: AdapterChaosScenario,
    *,
    page_id: str = "12345",
    base_url: str = "https://example.com/wiki",
) -> ConfluenceHTTPChaos:
    """Install a Confluence chaos scenario and return the configured helper."""
    chaos = ConfluenceHTTPChaos(
        scenario=scenario,
        page_id=page_id,
        base_url=base_url,
    )
    chaos.install(monkeypatch)
    return chaos


def _request_url(request: object) -> str:
    if isinstance(request, Request):
        return request.full_url
    if isinstance(request, str):
        return request
    return "https://example.com/unknown-chaos-request"


def _partial_page_payload(chaos: ConfluenceHTTPChaos) -> dict[str, object]:
    return {
        "id": chaos.page_id,
        "title": "Partial Chaos Page",
        "version": {
            "number": 1,
            "when": "2026-04-20T12:34:56Z",
        },
        "_links": {
            "base": chaos.base_url,
            "webui": f"/spaces/CHAOS/pages/{chaos.page_id}",
        },
    }
