from __future__ import annotations

import pytest

from knowledge_adapters.confluence.pacing import (
    ConfluenceRequestPacer,
    build_confluence_request_pacer,
    request_pacing_interval_seconds,
)


def test_build_request_pacer_defaults_to_noop_when_unconfigured() -> None:
    assert (
        build_confluence_request_pacer(
            request_delay_ms=None,
            max_requests_per_second=None,
        )
        is None
    )
    assert (
        build_confluence_request_pacer(
            request_delay_ms=0,
            max_requests_per_second=None,
        )
        is None
    )


def test_request_pacing_interval_uses_slower_option_when_both_are_set() -> None:
    assert (
        request_pacing_interval_seconds(
            request_delay_ms=250,
            max_requests_per_second=10,
        )
        == 0.25
    )
    assert (
        request_pacing_interval_seconds(
            request_delay_ms=10,
            max_requests_per_second=2,
        )
        == 0.5
    )


def test_request_pacer_sleeps_between_request_starts() -> None:
    now = 100.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    pacer = ConfluenceRequestPacer(
        min_interval_seconds=0.25,
        monotonic=monotonic,
        sleep=sleep,
    )

    pacer.pace()
    now += 0.1
    pacer.pace()
    now += 0.25
    pacer.pace()

    assert sleeps == [pytest.approx(0.15)]
