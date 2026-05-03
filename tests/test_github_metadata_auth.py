from __future__ import annotations

import pytest
from pytest import MonkeyPatch

from knowledge_adapters.github_metadata.auth import (
    DEFAULT_AUTH_STRATEGY,
    SUPPORTED_AUTH_STRATEGIES,
    build_request_auth,
    select_auth_strategy,
)


def test_github_metadata_auth_strategy_selection_keeps_stable_default() -> None:
    assert DEFAULT_AUTH_STRATEGY == "token-env"
    assert SUPPORTED_AUTH_STRATEGIES == ("token-env",)
    assert select_auth_strategy("token-env").name == "token-env"


def test_github_metadata_auth_strategy_selection_rejects_unknown_strategy() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported GitHub metadata auth strategy 'oauth'. Use 'token-env'.",
    ):
        select_auth_strategy("oauth")


def test_github_metadata_token_env_strategy_builds_existing_headers(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", " secret-token ")

    request_auth = build_request_auth(" GH_TOKEN ")

    assert request_auth.token_env == "GH_TOKEN"
    assert request_auth.headers == {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer secret-token",
        "User-Agent": "knowledge-adapters-github-metadata",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def test_github_metadata_token_env_strategy_rejects_empty_env_name() -> None:
    with pytest.raises(ValueError, match="token_env must name a non-empty environment variable"):
        build_request_auth("   ")


def test_github_metadata_token_env_strategy_rejects_missing_token(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)

    with pytest.raises(ValueError, match="token_env 'GH_TOKEN' is not set"):
        build_request_auth("GH_TOKEN")
