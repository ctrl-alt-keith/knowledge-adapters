"""Data models for the Confluence adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedTarget:
    """Canonical target representation for a source resource."""

    raw_value: str
    page_id: str | None
    page_url: str | None
