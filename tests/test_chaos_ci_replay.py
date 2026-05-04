from __future__ import annotations

from pathlib import Path


def test_make_chaos_random_uses_github_sha_seed_in_ci() -> None:
    makefile = Path("Makefile").read_text()

    assert 'if [ -n "$$GITHUB_SHA" ]; then' in makefile
    assert 'seed="ci-$$GITHUB_SHA";' in makefile


def test_make_chaos_targets_print_searchable_replay_command() -> None:
    makefile = Path("Makefile").read_text()

    assert "CHAOS_REPLAY_COMMAND: $$replay_command" in makefile
    assert "build_chaos_replay_command" in makefile


def test_chaos_failure_summary_uses_searchable_labels() -> None:
    conftest = Path("tests/conftest.py").read_text()

    assert "CHAOS_FAILURE_FINGERPRINT:" in conftest
    assert "CHAOS_FAILURE_REPLAY_COMMAND:" in conftest
