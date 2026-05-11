"""Configuration models for the public PDF/report adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicPdfConfig:
    """Runtime configuration for the public PDF/report adapter."""

    url: str
    output_dir: str
    dry_run: bool = False
