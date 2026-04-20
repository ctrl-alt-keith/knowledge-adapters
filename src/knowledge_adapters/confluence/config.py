"""Configuration models for the Confluence adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfluenceConfig:
    """Runtime configuration for the Confluence adapter."""

    base_url: str
    target: str
    output_dir: str
    client_mode: str = "stub"
    auth_method: str = "bearer-env"
    debug: bool = False
    dry_run: bool = False
    tree: bool = False
    max_depth: int = 0
