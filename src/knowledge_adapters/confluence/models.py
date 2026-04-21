"""Data models for the Confluence adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ResolvedTarget:
    """Canonical target representation for a source resource."""

    raw_value: str
    page_id: str | None
    page_url: str | None
    input_kind: Literal["page_id", "url", "empty", "invalid_url", "unknown"] = "unknown"
