"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pytest import MonkeyPatch

from tests.chaos import (
    AdapterChaosScenario,
    ConfluenceHTTPChaos,
    install_confluence_http_chaos,
)


@pytest.fixture
def confluence_chaos(
    monkeypatch: MonkeyPatch,
) -> Callable[[AdapterChaosScenario], ConfluenceHTTPChaos]:
    """Install one deterministic Confluence HTTP chaos scenario for a test."""

    def install(scenario: AdapterChaosScenario) -> ConfluenceHTTPChaos:
        return install_confluence_http_chaos(monkeypatch, scenario)

    return install
