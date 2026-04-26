"""Configuration models for the github_metadata adapter."""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_RESOURCE_TYPES = frozenset({"issue", "pull_request"})


@dataclass(frozen=True)
class GitHubMetadataConfig:
    """Runtime configuration for the github_metadata adapter."""

    repo: str
    token_env: str
    output_dir: str
    resource_type: str = "issue"
    base_url: str | None = None
    state: str = "open"
    since: str | None = None
    max_items: int | None = None
    include_issue_comments: bool = False
    dry_run: bool = False
