"""Run-scoped metrics for Confluence adapter executions."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class ConfluenceRunMetrics:
    """Lightweight counters and timers for one Confluence CLI run."""

    listing_requests: int = 0
    pages_discovered: int = 0
    discovery_seconds: float = 0.0
    page_fetch_requests: int = 0
    fetch_cache_hits: int = 0
    fetch_cache_misses: int = 0
    fetch_seconds: float = 0.0
    live_api_requests: int = 0

    @property
    def fetch_cache_saved_requests(self) -> int:
        """Return full-page fetch requests avoided by cache hits."""
        return self.fetch_cache_hits

    @property
    def request_timing_seconds(self) -> float:
        """Return elapsed time tracked around live request paths."""
        return self.discovery_seconds + self.fetch_seconds

    @property
    def effective_requests_per_second(self) -> float | None:
        """Return live Confluence API request rate when it can be computed."""
        if self.live_api_requests == 0 or self.request_timing_seconds <= 0:
            return None
        return self.live_api_requests / self.request_timing_seconds

    def record_live_api_request(self) -> None:
        self.live_api_requests += 1

    def record_listing_request(self) -> None:
        self.listing_requests += 1

    def record_page_fetch_request(self) -> None:
        self.page_fetch_requests += 1

    def record_pages_discovered(self, count: int) -> None:
        self.pages_discovered = count

    def record_fetch_cache_stats(self, *, hits: int, misses: int) -> None:
        self.fetch_cache_hits = hits
        self.fetch_cache_misses = misses

    @contextmanager
    def time_discovery(self) -> Iterator[None]:
        started_at = time.monotonic()
        try:
            yield
        finally:
            self.discovery_seconds += time.monotonic() - started_at

    @contextmanager
    def time_fetch(self) -> Iterator[None]:
        started_at = time.monotonic()
        try:
            yield
        finally:
            self.fetch_seconds += time.monotonic() - started_at
