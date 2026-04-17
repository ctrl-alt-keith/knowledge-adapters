"""Manifest handling for the Confluence adapter."""

from __future__ import annotations

from pathlib import Path


def manifest_path(output_dir: str) -> Path:
    """Return the manifest path for an output directory."""
    return Path(output_dir) / "manifest.json"