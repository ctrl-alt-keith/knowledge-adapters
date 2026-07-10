"""Reusable models for the Source Package contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ItemOutcome(StrEnum):
    COMPLETED = "completed"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AdapterIdentity:
    name: str
    version: str
    revision: str | None = None

    def as_dict(self) -> dict[str, str]:
        value = {"name": self.name, "version": self.version}
        if self.revision is not None:
            value["revision"] = self.revision
        return value


@dataclass(frozen=True)
class Artifact:
    path: str
    data: bytes
    role: str
    media_type: str


@dataclass(frozen=True)
class ArtifactInventoryEntry:
    path: str
    role: str
    media_type: str
    bytes: int
    sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "role": self.role,
            "media_type": self.media_type,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class PackageItem:
    item_id: str
    resource_kind: str
    outcome: ItemOutcome
    fields: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "resource_kind": self.resource_kind,
            "outcome": self.outcome.value,
            **self.fields,
        }
