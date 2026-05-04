"""Deterministic chaos helpers for adapter tests.

These helpers are test/dev-only seams for exercising adapter failure behavior
without real services, credentials, sleeps, or external network calls. Prefer
installing a named scenario in an adapter test over hand-rolling one-off HTTP
stubs so failure coverage stays readable and repeatable.
"""

from __future__ import annotations

import json
import random
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from enum import StrEnum
from hashlib import sha256
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


CHAOS_FINGERPRINT_VERSION = "chaos-v1"


@dataclass(frozen=True)
class ChaosFailureFingerprint:
    """Stable identifier and payload for a chaos validation failure."""

    identifier: str
    payload: Mapping[str, str]

    def as_line(self) -> str:
        """Return a compact, copyable fingerprint line."""
        payload_json = json.dumps(self.payload, sort_keys=True, separators=(",", ":"))
        return f"{self.identifier} {payload_json}"


def select_chaos_scenario(seed: str) -> AdapterChaosScenario:
    """Select one named chaos scenario deterministically from a seed."""
    return random.Random(seed).choice(tuple(AdapterChaosScenario))


def build_chaos_failure_fingerprint(
    *,
    scenario: str,
    nodeid: str,
    failure_type: str,
    failure_message: str,
    command_context: str,
) -> ChaosFailureFingerprint:
    """Build a deterministic fingerprint for comparing repeated chaos failures."""
    payload = {
        "command_context": _normalize_fingerprint_text(command_context),
        "failure_message": _normalize_fingerprint_text(failure_message),
        "failure_type": _normalize_fingerprint_text(failure_type),
        "nodeid": _normalize_fingerprint_text(nodeid),
        "scenario": _normalize_fingerprint_text(scenario),
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = sha256(payload_json.encode("utf-8")).hexdigest()[:16]
    return ChaosFailureFingerprint(
        identifier=f"{CHAOS_FINGERPRINT_VERSION}:{digest}",
        payload=payload,
    )


def build_chaos_command_context(*, target: str, seed: str | None, scenario: str) -> str:
    """Describe the Make command context that selected the failing chaos run."""
    if target == "chaos-random":
        parts = ["make", "chaos-random"]
        if seed:
            parts.append(f"CHAOS_SEED={shlex.quote(seed)}")
        parts.append(f"CHAOS_SCENARIO={shlex.quote(scenario)}")
        return " ".join(parts)
    if target == "chaos-all":
        return "make chaos-all"
    if target == "chaos-replay":
        parts = ["make", "chaos-replay"]
        if seed:
            parts.append(f"CHAOS_SEED={shlex.quote(seed)}")
        parts.append(f"CHAOS_SCENARIO={shlex.quote(scenario)}")
        return " ".join(parts)
    return target or "pytest -m chaos"


def build_chaos_replay_command(
    *,
    seed: str | None,
    scenario: str,
    nodeid: str | None = None,
) -> str:
    """Build a shell-safe Make command that replays one chaos failure."""
    parts = ["make", "chaos-replay"]
    if seed:
        parts.append(f"CHAOS_SEED={shlex.quote(seed)}")
    parts.append(f"CHAOS_SCENARIO={shlex.quote(scenario)}")
    if nodeid:
        parts.append(f"CHAOS_NODEID={shlex.quote(nodeid)}")
    return " ".join(parts)


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


def _normalize_fingerprint_text(value: str) -> str:
    return " ".join(value.split())


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
