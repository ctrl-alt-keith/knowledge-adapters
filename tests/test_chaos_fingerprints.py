from __future__ import annotations

from tests.chaos import (
    build_chaos_command_context,
    build_chaos_failure_fingerprint,
    build_chaos_replay_command,
)


def test_chaos_failure_fingerprint_is_deterministic() -> None:
    fingerprint = build_chaos_failure_fingerprint(
        scenario="timeout",
        nodeid="tests/confluence/test_chaos.py::test_failure[timeout]",
        failure_type="AssertionError",
        failure_message="expected timeout\n  got rate limit",
        command_context="make chaos-random CHAOS_SEED=issue-247 CHAOS_SCENARIO=timeout",
    )
    repeated = build_chaos_failure_fingerprint(
        scenario="timeout",
        nodeid="tests/confluence/test_chaos.py::test_failure[timeout]",
        failure_type="AssertionError",
        failure_message="expected timeout   got rate limit",
        command_context="make chaos-random CHAOS_SEED=issue-247 CHAOS_SCENARIO=timeout",
    )

    assert fingerprint == repeated
    assert fingerprint.identifier == "chaos-v1:001a8e93f7b5fb08"
    assert fingerprint.payload == {
        "command_context": "make chaos-random CHAOS_SEED=issue-247 CHAOS_SCENARIO=timeout",
        "failure_message": "expected timeout got rate limit",
        "failure_type": "AssertionError",
        "nodeid": "tests/confluence/test_chaos.py::test_failure[timeout]",
        "scenario": "timeout",
    }


def test_chaos_failure_fingerprint_changes_for_distinct_failures() -> None:
    timeout = build_chaos_failure_fingerprint(
        scenario="timeout",
        nodeid="tests/confluence/test_chaos.py::test_failure[timeout]",
        failure_type="AssertionError",
        failure_message="expected timeout",
        command_context="make chaos-random CHAOS_SEED=issue-247 CHAOS_SCENARIO=timeout",
    )
    rate_limit = build_chaos_failure_fingerprint(
        scenario="rate_limit",
        nodeid="tests/confluence/test_chaos.py::test_failure[rate_limit]",
        failure_type="AssertionError",
        failure_message="expected rate limit",
        command_context="make chaos-random CHAOS_SEED=issue-247 CHAOS_SCENARIO=rate_limit",
    )

    assert timeout.identifier != rate_limit.identifier


def test_chaos_replay_command_quotes_node_ids() -> None:
    command = build_chaos_replay_command(
        seed="issue 247",
        scenario="timeout",
        nodeid="tests/confluence/test_chaos.py::test_failure[timeout]",
    )

    assert command == (
        "make chaos-replay CHAOS_SEED='issue 247' CHAOS_SCENARIO=timeout "
        "CHAOS_NODEID='tests/confluence/test_chaos.py::test_failure[timeout]'"
    )


def test_chaos_replay_command_can_target_scenario_only() -> None:
    command = build_chaos_replay_command(
        seed="ci abc123",
        scenario="rate_limit",
    )

    assert command == "make chaos-replay CHAOS_SEED='ci abc123' CHAOS_SCENARIO=rate_limit"


def test_chaos_command_context_describes_make_target() -> None:
    assert (
        build_chaos_command_context(
            target="chaos-random",
            seed="issue 247",
            scenario="timeout",
        )
        == "make chaos-random CHAOS_SEED='issue 247' CHAOS_SCENARIO=timeout"
    )
