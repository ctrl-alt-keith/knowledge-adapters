"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import cast

import pytest
from _pytest.reports import TestReport
from _pytest.stash import StashKey
from _pytest.terminal import TerminalReporter
from pluggy import Result
from pytest import MonkeyPatch

from tests.chaos import (
    AdapterChaosScenario,
    ConfluenceHTTPChaos,
    build_chaos_command_context,
    build_chaos_failure_fingerprint,
    build_chaos_replay_command,
    install_confluence_http_chaos,
)


@dataclass(frozen=True)
class ChaosFailureReport:
    """Terminal summary details for one failed chaos test."""

    fingerprint_line: str
    replay_command: str


CHAOS_FAILURES_KEY = StashKey[list[ChaosFailureReport]]()


def pytest_configure(config: pytest.Config) -> None:
    config.stash[CHAOS_FAILURES_KEY] = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[object],
) -> Generator[None]:
    outcome = cast(Result[TestReport], (yield))
    report = outcome.get_result()

    if not report.failed or item.get_closest_marker("chaos") is None:
        return

    scenario = _chaos_scenario_for_item(item)
    failure_type, failure_message = _chaos_failure_details(call, report)
    seed = os.environ.get("CHAOS_SEED")
    command_context = build_chaos_command_context(
        target=os.environ.get("CHAOS_TARGET", ""),
        seed=seed,
        scenario=scenario,
    )
    fingerprint = build_chaos_failure_fingerprint(
        scenario=scenario,
        nodeid=report.nodeid,
        failure_type=failure_type,
        failure_message=failure_message,
        command_context=command_context,
    )

    item.config.stash[CHAOS_FAILURES_KEY].append(
        ChaosFailureReport(
            fingerprint_line=fingerprint.as_line(),
            replay_command=build_chaos_replay_command(
                seed=seed,
                scenario=scenario,
                nodeid=report.nodeid,
            ),
        )
    )


def pytest_terminal_summary(
    terminalreporter: TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    del exitstatus
    failures = config.stash[CHAOS_FAILURES_KEY]
    if not failures:
        return

    terminalreporter.section("chaos failure replay")
    for failure in failures:
        terminalreporter.write_line(f"fingerprint: {failure.fingerprint_line}")
        terminalreporter.write_line(f"replay: {failure.replay_command}")


@pytest.fixture
def confluence_chaos(
    monkeypatch: MonkeyPatch,
) -> Callable[[AdapterChaosScenario], ConfluenceHTTPChaos]:
    """Install one deterministic Confluence HTTP chaos scenario for a test."""

    def install(scenario: AdapterChaosScenario) -> ConfluenceHTTPChaos:
        return install_confluence_http_chaos(monkeypatch, scenario)

    return install


def _chaos_scenario_for_item(item: pytest.Item) -> str:
    callspec = getattr(item, "callspec", None)
    params = getattr(callspec, "params", {})
    if isinstance(params, dict) and "scenario" in params:
        scenario = params["scenario"]
        if isinstance(scenario, AdapterChaosScenario):
            return scenario.value
        return str(scenario)

    scenario = os.environ.get("CHAOS_SCENARIO")
    if scenario:
        return scenario

    return "unknown"


def _chaos_failure_details(
    call: pytest.CallInfo[object],
    report: TestReport,
) -> tuple[str, str]:
    if call.excinfo is None:
        return report.outcome, report.longreprtext

    failure_type = type(call.excinfo.value).__name__
    failure_message = str(call.excinfo.value).strip() or report.longreprtext
    return failure_type, failure_message
