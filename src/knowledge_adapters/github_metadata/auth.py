"""Authentication helpers for the github_metadata adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

GITHUB_API_VERSION = "2022-11-28"
DEFAULT_AUTH_STRATEGY = "token-env"


@dataclass(frozen=True)
class RequestAuth:
    """Request auth material for github_metadata API reads."""

    headers: dict[str, str]
    token_env: str


class GitHubMetadataAuthStrategy(Protocol):
    """Small interface for GitHub metadata request auth construction."""

    @property
    def name(self) -> str:
        """Stable configuration name for this strategy."""

    def build_request_auth(self, *, token_env: str) -> RequestAuth:
        """Build request auth material for this strategy."""


@dataclass(frozen=True)
class TokenEnvAuthStrategy:
    """Build bearer-token auth from the configured token environment variable."""

    name: str = DEFAULT_AUTH_STRATEGY

    def build_request_auth(self, *, token_env: str) -> RequestAuth:
        token_env_name, token = resolve_token(token_env)
        return RequestAuth(
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "knowledge-adapters-github-metadata",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            token_env=token_env_name,
        )


_AUTH_STRATEGIES: dict[str, GitHubMetadataAuthStrategy] = {
    DEFAULT_AUTH_STRATEGY: TokenEnvAuthStrategy(),
}
SUPPORTED_AUTH_STRATEGIES = tuple(_AUTH_STRATEGIES)


def select_auth_strategy(auth_strategy: str) -> GitHubMetadataAuthStrategy:
    """Select a supported GitHub metadata auth strategy by stable config name."""
    try:
        return _AUTH_STRATEGIES[auth_strategy]
    except KeyError as exc:
        supported_values = " or ".join(repr(strategy) for strategy in SUPPORTED_AUTH_STRATEGIES)
        raise ValueError(
            f"Unsupported GitHub metadata auth strategy {auth_strategy!r}. Use {supported_values}."
        ) from exc


def build_request_auth(
    token_env: str,
    *,
    auth_strategy: str = DEFAULT_AUTH_STRATEGY,
) -> RequestAuth:
    """Build auth material for a supported GitHub metadata auth strategy."""
    return select_auth_strategy(auth_strategy).build_request_auth(token_env=token_env)


def resolve_token(token_env: str) -> tuple[str, str]:
    """Resolve the GitHub token from an environment variable name."""
    normalized_token_env = token_env.strip()
    if not normalized_token_env:
        raise ValueError("token_env must name a non-empty environment variable.")

    token = os.getenv(normalized_token_env)
    if token is None or not token.strip():
        raise ValueError(
            f"token_env {normalized_token_env!r} is not set or contains an empty value."
        )
    return normalized_token_env, token.strip()
