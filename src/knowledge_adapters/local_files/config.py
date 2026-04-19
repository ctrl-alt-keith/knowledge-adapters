"""Configuration models for the local files adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalFilesConfig:
    """Runtime configuration for the local files adapter."""

    file_path: str
    output_dir: str
    dry_run: bool = False
