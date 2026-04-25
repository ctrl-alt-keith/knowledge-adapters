"""Configuration models for the git_repo adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitRepoConfig:
    """Runtime configuration for the git_repo adapter."""

    repo_url: str
    output_dir: str
    ref: str | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    subdir: str | None = None
    dry_run: bool = False
