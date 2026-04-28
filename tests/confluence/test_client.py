from __future__ import annotations

import json
from typing import Literal

from pytest import MonkeyPatch

from knowledge_adapters.confluence.client import (
    fetch_real_page,
    fetch_real_page_summary,
    list_real_child_page_ids,
    list_real_space_page_ids,
)
from knowledge_adapters.confluence.models import ResolvedTarget


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


def _real_target(page_id: str = "12345") -> ResolvedTarget:
    return ResolvedTarget(
        raw_value=page_id,
        page_id=page_id,
        page_url=None,
    )


def _valid_child_list_payload(*, child_page_ids: list[str]) -> dict[str, object]:
    return {
        "results": [
            {
                "id": child_page_id,
            }
            for child_page_id in child_page_ids
        ]
    }


def _valid_space_page_list_payload(
    *,
    page_ids: list[str],
    next_url: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "results": [{"id": page_id, "type": "page"} for page_id in page_ids]
    }
    if next_url is not None:
        payload["_links"] = {"next": next_url}
    return payload


def _valid_confluence_payload(page_id: str = "12345") -> dict[str, object]:
    return {
        "id": page_id,
        "title": "Real Page",
        "body": {"storage": {"value": "<p>Hello from Confluence.</p>"}},
        "version": {
            "number": 7,
            "when": "2026-04-20T12:34:56Z",
        },
        "_links": {
            "base": "https://example.com/wiki",
            "webui": f"/spaces/ENG/pages/{page_id}",
        },
    }


def test_real_child_list_reports_periodic_progress_for_large_results(
    monkeypatch: MonkeyPatch,
) -> None:
    progress_updates: list[int] = []

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            _valid_child_list_payload(
                child_page_ids=[str(page_id) for page_id in range(200, 1201)]
            )
        ),
    )

    child_page_ids = list_real_child_page_ids(
        _real_target(),
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        progress_callback=progress_updates.append,
    )

    assert len(child_page_ids) == 1001
    assert progress_updates == [500, 1000]


def test_real_child_list_does_not_report_progress_for_small_results(
    monkeypatch: MonkeyPatch,
) -> None:
    progress_updates: list[int] = []

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            _valid_child_list_payload(child_page_ids=["200", "300", "300"])
        ),
    )

    list_real_child_page_ids(
        _real_target(),
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        progress_callback=progress_updates.append,
    )

    assert progress_updates == []


def test_real_space_page_list_reports_periodic_progress_during_pagination(
    monkeypatch: MonkeyPatch,
) -> None:
    progress_updates: list[int] = []
    payloads = [
        _valid_space_page_list_payload(
            page_ids=[str(page_id) for page_id in range(1, 401)],
            next_url="/wiki/rest/api/content?spaceKey=ENG&type=page&start=400&limit=400",
        ),
        _valid_space_page_list_payload(
            page_ids=[str(page_id) for page_id in range(401, 801)],
            next_url="/wiki/rest/api/content?spaceKey=ENG&type=page&start=800&limit=400",
        ),
        _valid_space_page_list_payload(
            page_ids=[str(page_id) for page_id in range(801, 1101)]
        ),
    ]

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        del args, kwargs
        return _FakeHTTPResponse(payloads.pop(0))

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page_ids = list_real_space_page_ids(
        "ENG",
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        page_limit=400,
        progress_callback=progress_updates.append,
    )

    assert len(page_ids) == 1100
    assert progress_updates == [500, 1000]


def test_real_space_page_list_does_not_report_progress_for_small_runs(
    monkeypatch: MonkeyPatch,
) -> None:
    progress_updates: list[int] = []

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            _valid_space_page_list_payload(page_ids=["100", "200"])
        ),
    )

    list_real_space_page_ids(
        "ENG",
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        progress_callback=progress_updates.append,
    )

    assert progress_updates == []


def test_real_fetch_omits_pacing_by_default(monkeypatch: MonkeyPatch) -> None:
    request_count = 0

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        nonlocal request_count
        del args, kwargs
        request_count += 1
        return _FakeHTTPResponse(_valid_confluence_payload())

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page = fetch_real_page(
        _real_target(),
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
    )

    assert page["canonical_id"] == "12345"
    assert request_count == 1


def test_real_page_fetch_invokes_request_pacer(monkeypatch: MonkeyPatch) -> None:
    pacer_calls: list[str] = []

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(_valid_confluence_payload()),
    )

    page = fetch_real_page(
        _real_target(),
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        request_pacer=lambda: pacer_calls.append("fetch"),
    )

    assert page["canonical_id"] == "12345"
    assert pacer_calls == ["fetch"]


def test_real_page_summary_fetch_invokes_request_pacer(monkeypatch: MonkeyPatch) -> None:
    pacer_calls: list[str] = []

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(_valid_confluence_payload()),
    )

    page = fetch_real_page_summary(
        _real_target(),
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        request_pacer=lambda: pacer_calls.append("summary"),
    )

    assert page["canonical_id"] == "12345"
    assert "content" not in page
    assert pacer_calls == ["summary"]


def test_real_child_listing_invokes_request_pacer(monkeypatch: MonkeyPatch) -> None:
    pacer_calls: list[str] = []

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            _valid_child_list_payload(child_page_ids=["200"])
        ),
    )

    child_page_ids = list_real_child_page_ids(
        _real_target(),
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        request_pacer=lambda: pacer_calls.append("child-list"),
    )

    assert child_page_ids == ["200"]
    assert pacer_calls == ["child-list"]


def test_real_space_listing_invokes_request_pacer_for_each_page(
    monkeypatch: MonkeyPatch,
) -> None:
    pacer_calls: list[str] = []
    payloads = [
        _valid_space_page_list_payload(
            page_ids=["300", "100"],
            next_url="/wiki/rest/api/content?spaceKey=ENG&type=page&start=2&limit=2",
        ),
        _valid_space_page_list_payload(page_ids=["200"]),
    ]

    def fake_urlopen(*args: object, **kwargs: object) -> _FakeHTTPResponse:
        del args, kwargs
        return _FakeHTTPResponse(payloads.pop(0))

    monkeypatch.setenv("CONFLUENCE_BEARER_TOKEN", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    page_ids = list_real_space_page_ids(
        "ENG",
        base_url="https://example.com/wiki",
        auth_method="bearer-env",
        page_limit=2,
        request_pacer=lambda: pacer_calls.append("space-list"),
    )

    assert page_ids == ["100", "200", "300"]
    assert pacer_calls == ["space-list", "space-list"]
