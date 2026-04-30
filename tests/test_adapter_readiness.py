from __future__ import annotations

import pytest

from knowledge_adapters.adapter_readiness import (
    READINESS_DIMENSIONS,
    AdapterReadiness,
    adapter_readiness,
    render_adapter_readiness_report,
)


def test_adapter_readiness_model_is_sorted_and_complete() -> None:
    rows = adapter_readiness()
    dimension_keys = {dimension.key for dimension in READINESS_DIMENSIONS}

    assert tuple(row.adapter for row in rows) == (
        "confluence",
        "git_repo",
        "github_metadata",
        "local_files",
    )
    assert tuple(row.adapter for row in rows) == tuple(sorted(row.adapter for row in rows))
    for row in rows:
        assert set(row.coverage) == dimension_keys
        assert set(row.evidence) == dimension_keys

    confluence = rows[0]
    assert confluence.coverage == {
        "contract_invariant": True,
        "chaos": True,
        "replay": True,
        "no_partial_artifacts": True,
    }


def test_adapter_readiness_report_is_deterministic() -> None:
    report = render_adapter_readiness_report()

    assert report == render_adapter_readiness_report()
    assert report == (
        "Adapter Readiness Coverage\n"
        "\n"
        "Lightweight coverage map; not a quality score.\n"
        "\n"
        "Adapter          Contract/invariant  Chaos  Replay  No partial artifacts\n"
        "---------------  ------------------  -----  ------  --------------------\n"
        "confluence       yes                 yes    yes     yes\n"
        "git_repo         no                  no     no      no\n"
        "github_metadata  no                  no     no      no\n"
        "local_files      no                  no     no      no\n"
        "\n"
        "Evidence:\n"
        "confluence:\n"
        "  Contract/invariant: yes - tests/confluence/test_contracts.py uses "
        "tests.adapter_contracts helpers.\n"
        "  Chaos: yes - tests/confluence/test_chaos.py covers deterministic Confluence "
        "HTTP failures.\n"
        "  Replay: yes - make chaos-replay reruns named Confluence chaos scenarios.\n"
        "  No partial artifacts: yes - Confluence failure tests assert no manifest or "
        "markdown artifacts are written.\n"
        "git_repo:\n"
        "  Contract/invariant: no - Not yet registered in the readiness model.\n"
        "  Chaos: no - No git_repo chaos scenarios are registered.\n"
        "  Replay: no - Replay applies to registered chaos scenarios; git_repo has none.\n"
        "  No partial artifacts: no - No no-partial-artifact failure coverage is registered.\n"
        "github_metadata:\n"
        "  Contract/invariant: no - Not yet registered in the readiness model.\n"
        "  Chaos: no - No github_metadata chaos scenarios are registered.\n"
        "  Replay: no - Replay applies to registered chaos scenarios; github_metadata has none.\n"
        "  No partial artifacts: no - No no-partial-artifact failure coverage is registered.\n"
        "local_files:\n"
        "  Contract/invariant: no - Not yet registered in the readiness model.\n"
        "  Chaos: no - No local_files chaos scenarios are registered.\n"
        "  Replay: no - Replay applies to registered chaos scenarios; local_files has none.\n"
        "  No partial artifacts: no - No no-partial-artifact failure coverage is registered.\n"
    )


def test_adapter_readiness_report_rejects_incomplete_rows() -> None:
    row = AdapterReadiness(
        adapter="example",
        coverage={"chaos": True},
        evidence={"chaos": "Example evidence."},
    )

    with pytest.raises(ValueError, match="coverage keys"):
        render_adapter_readiness_report((row,))
