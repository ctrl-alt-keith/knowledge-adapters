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


class CollectionProgressState(StrEnum):
    """Observed exhaustion of the bounded collection scope in this request."""

    EXHAUSTED = "exhausted"
    CONTINUATION_REMAINING = "continuation_remaining"


@dataclass(frozen=True)
class CollectionProgress:
    state: CollectionProgressState

    def as_dict(self) -> dict[str, str]:
        return {"state": self.state.value}


@dataclass(frozen=True)
class PackageLineage:
    """Provider-neutral immutable lineage emitted into a sealed manifest."""

    resumes_run_id: str | None = None
    prior_package_ids: tuple[str, ...] = ()
    prior_run_ids: tuple[str, ...] = ()
    reconciliation_summary: dict[str, int] = field(default_factory=dict)
    final_attempt_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if self.resumes_run_id is not None:
            values["resumes_run_id"] = self.resumes_run_id
        if self.prior_package_ids:
            values["prior_package_ids"] = list(self.prior_package_ids)
        if self.prior_run_ids:
            values["prior_run_ids"] = list(self.prior_run_ids)
        if self.reconciliation_summary:
            values["reconciliation_summary"] = dict(self.reconciliation_summary)
        if self.final_attempt_counts:
            values["final_attempt_counts"] = dict(self.final_attempt_counts)
        return values


@dataclass(frozen=True)
class AcquisitionRequest:
    request_id: str
    adapter_type: str
    targets: tuple[str, ...]
    scope: dict[str, Any]
    output_location: str
    credential_reference: str | None = None
    selection: dict[str, Any] | None = None
    checkpoint_reference: str | None = None
    retry_policy: dict[str, Any] | None = None
    expected_contract: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "request_id": self.request_id,
            "adapter_type": self.adapter_type,
            "targets": list(self.targets),
            "scope": self.scope,
            "output_location": self.output_location,
        }
        for key in (
            "credential_reference",
            "selection",
            "checkpoint_reference",
            "retry_policy",
            "expected_contract",
        ):
            item = getattr(self, key)
            if item is not None:
                value[key] = item
        if self.extensions:
            value["extensions"] = self.extensions
        return value


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
        reserved = {"item_id", "resource_kind", "outcome"} & self.fields.keys()
        if reserved:
            raise ValueError(f"item fields contain reserved keys: {', '.join(sorted(reserved))}")
        return {
            "item_id": self.item_id,
            "resource_kind": self.resource_kind,
            "outcome": self.outcome.value,
            **self.fields,
        }
