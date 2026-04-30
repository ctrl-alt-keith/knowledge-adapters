from __future__ import annotations

import re
from pathlib import Path

import pytest

from knowledge_adapters.adapter_readiness import (
    READINESS_DIMENSIONS,
    AdapterReadiness,
    adapter_readiness,
    render_adapter_readiness_report,
)
from knowledge_adapters.cli import build_parser

NON_ADAPTER_CLI_COMMANDS = {"bundle", "run"}
REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH_RE = re.compile(
    r"\b(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:md|py)\b|\bMakefile\b"
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


def test_adapter_readiness_model_matches_adapter_cli_surfaces() -> None:
    adapter_commands = _adapter_cli_commands()
    readiness_adapters = {row.adapter for row in adapter_readiness()}

    assert readiness_adapters == adapter_commands


def test_adapter_readiness_evidence_paths_exist() -> None:
    evidence_paths = {
        path
        for row in adapter_readiness()
        for evidence in row.evidence.values()
        for path in _evidence_path_references(evidence)
    }

    assert evidence_paths == {
        "tests/confluence/test_chaos.py",
        "tests/confluence/test_contracts.py",
    }
    for path in evidence_paths:
        assert (REPO_ROOT / path).is_file(), path


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


def _adapter_cli_commands() -> set[str]:
    parser = build_parser()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return set(choices) - NON_ADAPTER_CLI_COMMANDS
    raise AssertionError("CLI parser has no subcommands.")


def _evidence_path_references(evidence: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in EVIDENCE_PATH_RE.finditer(evidence))
