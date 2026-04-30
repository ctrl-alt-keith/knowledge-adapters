from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from pytest import CaptureFixture

from knowledge_adapters.cli import main
from knowledge_adapters.confluence.client import ConfluenceRequestError, fetch_real_page
from knowledge_adapters.confluence.models import ResolvedTarget
from tests.adapter_contracts import assert_no_partial_adapter_artifacts
from tests.chaos import AdapterChaosScenario, ConfluenceHTTPChaos, select_chaos_scenario

ConfluenceChaosInstaller = Callable[[AdapterChaosScenario], ConfluenceHTTPChaos]

pytestmark = pytest.mark.chaos


def _target(page_id: str = "12345") -> ResolvedTarget:
    return ResolvedTarget(
        raw_value=page_id,
        page_id=page_id,
        page_url=None,
    )


def _confluence_cli_argv(output_dir: Path) -> list[str]:
    return [
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        str(output_dir),
        "--client-mode",
        "real",
    ]


@pytest.mark.parametrize(
    ("scenario", "expected_message"),
    [
        (
            AdapterChaosScenario.TIMEOUT,
            "Confluence network request failed. Verify --base-url and network access.",
        ),
        (
            AdapterChaosScenario.RATE_LIMIT,
            "Confluence request failed (status 429). Verify --base-url and access.",
        ),
    ],
)
def test_confluence_chaos_request_failures_are_clear(
    confluence_chaos: ConfluenceChaosInstaller,
    scenario: AdapterChaosScenario,
    expected_message: str,
) -> None:
    confluence_chaos(scenario)

    with pytest.raises(ConfluenceRequestError) as exc_info:
        fetch_real_page(
            _target(),
            base_url="https://example.com/wiki",
            auth_method="bearer-env",
        )

    exc = exc_info.value
    assert str(exc) == expected_message
    assert exc.request_url == (
        "https://example.com/wiki/rest/api/content/"
        "12345?expand=body.storage,_links,version"
    )
    assert exc.auth_method == "bearer-env"


@pytest.mark.parametrize(
    ("scenario", "expected_message"),
    [
        (
            AdapterChaosScenario.INVALID_JSON,
            "Response error: invalid JSON payload.",
        ),
        (
            AdapterChaosScenario.EMPTY_RESPONSE,
            "Response error: invalid JSON payload.",
        ),
        (
            AdapterChaosScenario.PARTIAL_PAYLOAD,
            "Response error: missing content.",
        ),
    ],
)
def test_confluence_chaos_payload_failures_are_clear(
    confluence_chaos: ConfluenceChaosInstaller,
    scenario: AdapterChaosScenario,
    expected_message: str,
) -> None:
    confluence_chaos(scenario)

    with pytest.raises(ValueError, match=expected_message):
        fetch_real_page(
            _target(),
            base_url="https://example.com/wiki",
            auth_method="bearer-env",
        )


@pytest.mark.parametrize(
    ("scenario", "expected_message"),
    [
        (
            AdapterChaosScenario.TIMEOUT,
            "Confluence network request failed. Verify --base-url and network access.",
        ),
        (
            AdapterChaosScenario.RATE_LIMIT,
            "Confluence request failed (status 429). Verify --base-url and access.",
        ),
        (
            AdapterChaosScenario.INVALID_JSON,
            "Response error: invalid JSON payload.",
        ),
        (
            AdapterChaosScenario.EMPTY_RESPONSE,
            "Response error: invalid JSON payload.",
        ),
        (
            AdapterChaosScenario.PARTIAL_PAYLOAD,
            "Response error: missing content.",
        ),
    ],
)
def test_confluence_cli_real_mode_surfaces_chaos_without_artifacts(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    confluence_chaos: ConfluenceChaosInstaller,
    scenario: AdapterChaosScenario,
    expected_message: str,
) -> None:
    confluence_chaos(scenario)
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        main(_confluence_cli_argv(output_dir))

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"knowledge-adapters confluence: error: {expected_message}\n"
    assert_no_partial_adapter_artifacts(output_dir)


def test_chaos_random_selection_is_seeded() -> None:
    scenario = select_chaos_scenario("issue-247")

    assert scenario == select_chaos_scenario("issue-247")
    assert scenario in tuple(AdapterChaosScenario)
