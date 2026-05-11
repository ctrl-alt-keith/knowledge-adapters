"""Configuration models for the public webpage adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicWebpageConfig:
    """Runtime configuration for the public webpage adapter."""

    url: str
    output_dir: str
    dry_run: bool = False
