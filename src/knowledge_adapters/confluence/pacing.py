"""Optional request pacing for live Confluence API calls."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ConfluenceRequestPacer:
    """Enforce a minimum interval between real Confluence request starts."""

    min_interval_seconds: float
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_request_started_at: float | None = field(default=None, init=False)

    def pace(self) -> None:
        now = self.monotonic()
        if self._last_request_started_at is not None:
            elapsed = now - self._last_request_started_at
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                self.sleep(remaining)
                now = self.monotonic()
        self._last_request_started_at = now


def request_pacing_interval_seconds(
    *,
    request_delay_ms: int | None,
    max_requests_per_second: float | None,
) -> float | None:
    """Return the configured request interval, using the slower option when both are set."""
    intervals: list[float] = []
    if request_delay_ms is not None and request_delay_ms > 0:
        intervals.append(request_delay_ms / 1000)
    if max_requests_per_second is not None:
        intervals.append(1 / max_requests_per_second)
    if not intervals:
        return None
    return max(intervals)


def build_confluence_request_pacer(
    *,
    request_delay_ms: int | None,
    max_requests_per_second: float | None,
) -> ConfluenceRequestPacer | None:
    """Build an optional Confluence request pacer from validated config values."""
    interval_seconds = request_pacing_interval_seconds(
        request_delay_ms=request_delay_ms,
        max_requests_per_second=max_requests_per_second,
    )
    if interval_seconds is None:
        return None
    return ConfluenceRequestPacer(interval_seconds)
