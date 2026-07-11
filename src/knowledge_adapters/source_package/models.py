"""Reusable models for the Source Package contract."""

from __future__ import annotations

from collections.abc import Mapping
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
    reconciliation_summary: Mapping[str, int] | None = None
    final_attempt_counts: Mapping[str, int] | None = None

    def as_dict(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if self.resumes_run_id is not None:
            values["resumes_run_id"] = self.resumes_run_id
        if self.prior_package_ids:
            values["prior_package_ids"] = list(self.prior_package_ids)
        if self.prior_run_ids:
            values["prior_run_ids"] = list(self.prior_run_ids)
        if self.reconciliation_summary is not None:
            values["reconciliation_summary"] = dict(self.reconciliation_summary)
        if self.final_attempt_counts is not None:
            values["final_attempt_counts"] = dict(self.final_attempt_counts)
        return values

    def validated_dict(self, *, package_id: str, run_id: str) -> dict[str, Any]:
        """Return manifest lineage after validating producer-owned invariants."""
        for field_name, identifiers in (
            ("prior_package_ids", self.prior_package_ids),
            ("prior_run_ids", self.prior_run_ids),
        ):
            if any(not isinstance(value, str) or not value for value in identifiers):
                raise ValueError(f"{field_name} must contain non-empty strings")
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{field_name} must not contain duplicates")
        if package_id in self.prior_package_ids:
            raise ValueError("prior_package_ids must not contain the current package_id")
        if self.resumes_run_id is not None:
            if not isinstance(self.resumes_run_id, str) or not self.resumes_run_id:
                raise ValueError("resumes_run_id must be a non-empty string")
            if self.resumes_run_id == run_id:
                raise ValueError("resumes_run_id must not equal the current run_id")
            if self.resumes_run_id not in self.prior_run_ids:
                raise ValueError("resumes_run_id must appear in prior_run_ids")
            if self.reconciliation_summary is None:
                raise ValueError("resumed lineage requires reconciliation_summary")
            if self.final_attempt_counts is None:
                raise ValueError("resumed lineage requires final_attempt_counts")
        if run_id in self.prior_run_ids:
            raise ValueError("prior_run_ids must not contain the current run_id")
        for field_name, values in (
            ("reconciliation_summary", self.reconciliation_summary),
            ("final_attempt_counts", self.final_attempt_counts),
        ):
            if values is not None and any(
                not isinstance(key, str)
                or not key
                or type(value) is not int
                or value < 0
                for key, value in values.items()
            ):
                raise ValueError(f"{field_name} must contain nonnegative integer values")
        return self.as_dict()


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
