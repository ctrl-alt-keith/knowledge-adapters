"""Deterministic Source Package assembly, sealing, and verification."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any

from .models import (
    AcquisitionRequest,
    AdapterIdentity,
    Artifact,
    ArtifactInventoryEntry,
    ItemOutcome,
    PackageItem,
)

_ORIGINAL_PATH_READ_BYTES = Path.read_bytes

CONTRACT_NAME = "knowledge-source-package"
RESULT_SCHEMA_VERSION = "2.2.0"
SIDECAR_RE = re.compile(rb"[0-9a-f]{64}\n\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
RESERVED_MANIFEST_FIELDS = frozenset(
    {
        "contract_name",
        "contract_version",
        "package_id",
        "request_id",
        "run_id",
        "created_at",
        "adapter",
        "boundary",
        "required_capabilities",
        "status",
        "counts",
        "items",
        "artifacts",
        "request_path",
        "run_receipt",
        "resumes_run_id",
        "prior_package_ids",
        "prior_run_ids",
        "reconciliation_summary",
        "final_attempt_counts",
        "lineage",
        "integrity",
        "content_address",
    }
)


def _library_version() -> str | None:
    try:
        return version("knowledge-adapters")
    except PackageNotFoundError:
        return None


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON deterministically as UTF-8, with one trailing newline."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _safe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == value
        and not value.startswith("./")
        and "//" not in value
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_stable_read(path: Path, limit: int) -> bytes:
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise OSError("entry is not a bounded regular file")
    injected_read = Path.read_bytes is not _ORIGINAL_PATH_READ_BYTES
    if injected_read:
        # Preserve the verifier's established deterministic I/O fault-injection seam.
        data = path.read_bytes()
    else:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    after = path.stat(follow_symlinks=False)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if len(data) > limit or identity_before != identity_after or (
        not injected_read and len(data) != after.st_size
    ):
        raise OSError("entry changed during bounded read")
    return data


class VerificationState(StrEnum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    INDETERMINATE_IO = "indeterminate_io"


class VerificationStage(StrEnum):
    ENVELOPE = "envelope"
    SIDECAR_FORMAT = "sidecar-format"
    MANIFEST_DIGEST = "manifest-digest"
    MANIFEST_PARSE = "manifest-parse"
    COMPATIBILITY = "compatibility"
    PATH_SAFETY = "path-safety"
    INVENTORY_COVERAGE = "inventory-coverage"
    TERMINAL_ACCOUNTING = "terminal-accounting"
    ITEM_SEMANTICS = "item-semantics"
    LINEAGE = "lineage"
    ARTIFACT_INTEGRITY = "artifact-integrity"
    COMPLETE = "complete"


STAGE_ORDER = tuple(VerificationStage)


class FindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ConsumerProfile:
    """Provider-neutral resource and compatibility limits for package verification."""

    identifier: str = "default-v1"
    supported_major_versions: tuple[int, ...] = (1,)
    supported_capabilities: tuple[str, ...] = ()
    max_manifest_bytes: int = 4 * 1024 * 1024
    max_sidecar_bytes: int = 65
    max_json_depth: int = 64
    max_package_entries: int = 10_000
    max_item_records: int = 2_000
    max_artifacts: int = 10_000
    max_diagnostics: int = 2_000
    max_file_bytes: int = 64 * 1024 * 1024
    max_aggregate_bytes: int = 512 * 1024 * 1024
    max_path_length: int = 1024
    max_path_components: int = 32

    def __post_init__(self) -> None:
        values = (
            self.max_manifest_bytes,
            self.max_sidecar_bytes,
            self.max_json_depth,
            self.max_package_entries,
            self.max_item_records,
            self.max_artifacts,
            self.max_diagnostics,
            self.max_file_bytes,
            self.max_aggregate_bytes,
            self.max_path_length,
            self.max_path_components,
        )
        if not self.identifier or len(self.identifier) > 100 or any(value <= 0 for value in values):
            raise ValueError("consumer profile identifiers and limits must be positive and bounded")
        if not self.supported_major_versions or any(
            value <= 0 for value in self.supported_major_versions
        ):
            raise ValueError("consumer profile must support at least one positive major version")


@dataclass(frozen=True)
class VerifiedArtifactClaim:
    path: str
    role: str
    media_type: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class VerifiedItemDisposition:
    item_id: str
    resource_kind: str
    outcome: str
    requested_locator: str | None = None
    resolved_locator: str | None = None
    canonical_locator: str | None = None
    provider: str | None = None
    provider_resource_id: str | None = None
    language: str | None = None
    artifact_references: tuple[str, ...] = ()
    diagnostic_references: tuple[str, ...] = ()
    associated_artifacts: tuple[VerifiedArtifactClaim, ...] = ()
    finding_references: tuple[str, ...] = ()
    normalization_name: str | None = None
    normalization_version: str | None = None
    normalization_transforms: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifiedPackageTotals:
    package_entries: int
    item_records: int
    artifacts: int
    diagnostics: int
    aggregate_bytes: int


@dataclass(frozen=True)
class SealResult:
    ok: bool
    package_path: Path | None = None
    content_address: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class VerificationFinding:
    code: str
    severity: FindingSeverity
    stage: VerificationStage
    message: str
    reference: str | None = None
    observed: str | int | None = None
    expected: str | int | None = None

    @property
    def path(self) -> str | None:
        """Backward-compatible alias for portable path/field references."""
        return self.reference


VerificationIssue = VerificationFinding


@dataclass(frozen=True)
class VerifiedAdapterClaims:
    name: str | None = None
    version: str | None = None
    revision: str | None = None


@dataclass(frozen=True)
class VerifiedManifestClaims:
    """Bounded, curated claims from verification stages that completed."""

    schema_version: str = "1.2.0"
    contract_name: str | None = None
    contract_version: str | None = None
    package_id: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    created_at: str | None = None
    adapter: VerifiedAdapterClaims | None = None
    status: str | None = None
    counts: Mapping[str, int] | None = None
    required_capabilities: tuple[str, ...] = ()
    item_references: tuple[str, ...] = ()
    request_reference: str | None = None
    resumes_run_id: str | None = None
    prior_run_ids: tuple[str, ...] = ()
    prior_package_ids: tuple[str, ...] = ()
    item_dispositions: tuple[VerifiedItemDisposition, ...] = ()
    artifact_inventory: tuple[VerifiedArtifactClaim, ...] = ()
    totals: VerifiedPackageTotals | None = None
    content_address: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    schema_version: str
    verifier_version: str | None
    state: VerificationState
    last_completed_stage: VerificationStage
    findings: tuple[VerificationFinding, ...]
    content_address: str | None = None
    verified_claims: VerifiedManifestClaims | None = None
    consumer_profile: str | None = None

    @property
    def ok(self) -> bool:
        return self.state is VerificationState.VERIFIED

    @property
    def issues(self) -> tuple[VerificationFinding, ...]:
        return self.findings

def _bounded(value: object, limit: int = 200) -> str:
    text = str(value).replace("\n", "\\n").replace("\r", "\\r")
    return text if len(text) <= limit else f"{text[:limit]}…"


def _finding(
    code: str,
    stage: VerificationStage,
    message: str,
    reference: str | None = None,
    observed: object | None = None,
    expected: object | None = None,
) -> VerificationFinding:
    return VerificationFinding(
        code,
        FindingSeverity.ERROR,
        stage,
        _bounded(message),
        reference,
        None if observed is None else _bounded(observed),
        None if expected is None else _bounded(expected),
    )


def _make_result(
    state: VerificationState,
    stage: VerificationStage,
    findings: Sequence[VerificationFinding] = (),
    content_address: str | None = None,
    claims: VerifiedManifestClaims | None = None,
    profile: ConsumerProfile | None = None,
) -> VerificationResult:
    completed_stage = stage
    if state is not VerificationState.VERIFIED:
        stage_index = STAGE_ORDER.index(stage)
        completed_stage = STAGE_ORDER[max(0, stage_index - 1)]
    return VerificationResult(
        RESULT_SCHEMA_VERSION,
        _library_version(),
        state,
        completed_stage,
        tuple(findings),
        content_address,
        claims,
        profile.identifier if profile is not None else None,
    )


def _bounded_claim(value: object, limit: int = 200) -> str | None:
    return value if isinstance(value, str) and len(value) <= limit else None


def _bounded_string_tuple(value: object, *, limit: int = 256) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        return ()
    if any(not isinstance(item, str) or len(item) > 200 for item in value):
        return ()
    return tuple(value)


def _verified_item_dispositions(
    parsed_items: Sequence[tuple[str, Mapping[str, Any]]],
    artifacts_by_path: Mapping[str, VerifiedArtifactClaim],
) -> tuple[VerifiedItemDisposition, ...]:
    values: list[VerifiedItemDisposition] = []
    for _, item in parsed_items:
        provenance = item.get("provenance")
        normalization = item.get("normalization")
        artifacts = _bounded_string_tuple(item.get("artifacts"), limit=256)
        diagnostics = _bounded_string_tuple(item.get("diagnostics"), limit=256)
        transforms: tuple[str, ...] = ()
        if isinstance(normalization, dict):
            transforms = _bounded_string_tuple(normalization.get("transforms"), limit=64)
        values.append(
            VerifiedItemDisposition(
                item_id=_bounded_claim(item.get("item_id")) or "",
                resource_kind=_bounded_claim(item.get("resource_kind")) or "",
                outcome=_bounded_claim(item.get("outcome")) or "",
                requested_locator=_bounded_claim(item.get("requested_locator"), 2048),
                resolved_locator=_bounded_claim(item.get("resolved_locator"), 2048),
                canonical_locator=_bounded_claim(item.get("canonical_locator"), 2048),
                provider=(
                    _bounded_claim(provenance.get("provider"))
                    if isinstance(provenance, dict)
                    else None
                ),
                provider_resource_id=(
                    _bounded_claim(provenance.get("provider_resource_id"))
                    if isinstance(provenance, dict)
                    else None
                ),
                language=_bounded_claim(item.get("language"), 64),
                artifact_references=artifacts,
                diagnostic_references=diagnostics,
                associated_artifacts=tuple(
                    artifacts_by_path[path] for path in artifacts if path in artifacts_by_path
                ),
                finding_references=(),
                normalization_name=(
                    _bounded_claim(normalization.get("name"))
                    if isinstance(normalization, dict)
                    else None
                ),
                normalization_version=(
                    _bounded_claim(normalization.get("version"))
                    if isinstance(normalization, dict)
                    else None
                ),
                normalization_transforms=transforms,
            )
        )
    return tuple(values)


def _curated_claims(
    manifest: Mapping[str, Any],
    content_address: str,
    *,
    accounting: bool = False,
    lineage: bool = False,
    item_dispositions: tuple[VerifiedItemDisposition, ...] = (),
    artifact_inventory: tuple[VerifiedArtifactClaim, ...] = (),
    totals: VerifiedPackageTotals | None = None,
) -> VerifiedManifestClaims:
    adapter_value = manifest.get("adapter")
    adapter = None
    if isinstance(adapter_value, dict):
        adapter = VerifiedAdapterClaims(
            _bounded_claim(adapter_value.get("name")),
            _bounded_claim(adapter_value.get("version")),
            _bounded_claim(adapter_value.get("revision")),
        )
    counts_value = manifest.get("counts")
    counts = None
    if accounting and isinstance(counts_value, dict):
        counts = {
            key: value
            for key, value in counts_value.items()
            if isinstance(key, str) and type(value) is int
        }
    return VerifiedManifestClaims(
        contract_name=_bounded_claim(manifest.get("contract_name")),
        contract_version=_bounded_claim(manifest.get("contract_version")),
        package_id=_bounded_claim(manifest.get("package_id")),
        request_id=_bounded_claim(manifest.get("request_id")),
        run_id=_bounded_claim(manifest.get("run_id")),
        created_at=_bounded_claim(manifest.get("created_at")),
        adapter=adapter,
        status=_bounded_claim(manifest.get("status")) if accounting else None,
        counts=counts,
        required_capabilities=_bounded_string_tuple(manifest.get("required_capabilities")),
        item_references=(
            _bounded_string_tuple(manifest.get("items"), limit=10_000) if accounting else ()
        ),
        request_reference=_bounded_claim(manifest.get("request_path")),
        resumes_run_id=(
            _bounded_claim(manifest.get("resumes_run_id")) if lineage else None
        ),
        prior_run_ids=(
            _bounded_string_tuple(manifest.get("prior_run_ids")) if lineage else ()
        ),
        prior_package_ids=(
            _bounded_string_tuple(manifest.get("prior_package_ids")) if lineage else ()
        ),
        item_dispositions=item_dispositions,
        artifact_inventory=artifact_inventory,
        totals=totals,
        content_address=content_address,
    )


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = item
    return value


def _json_depth(value: Any, depth: int = 1) -> int:
    if isinstance(value, dict):
        return max((_json_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value), default=depth)
    return depth


class PackageBuilder:
    """Collect a complete package in memory and atomically seal it once."""

    def __init__(
        self,
        *,
        package_id: str,
        request: AcquisitionRequest,
        run_id: str,
        created_at: str,
        adapter: AdapterIdentity,
        contract_version: str = "1.0.0",
        required_capabilities: Sequence[str] = (),
        boundary: Mapping[str, str],
        extensions: Mapping[str, Any] | None = None,
        manifest_fields: Mapping[str, Any] | None = None,
    ) -> None:
        if manifest_fields:
            reserved = RESERVED_MANIFEST_FIELDS & manifest_fields.keys()
            if reserved:
                raise ValueError(
                    f"manifest_fields contain reserved keys: {', '.join(sorted(reserved))}"
                )
            raise ValueError("manifest_fields is unsupported; use namespaced extensions")
        if not request.request_id:
            raise ValueError("request_id must not be empty")
        if extensions and any("." not in key for key in extensions):
            raise ValueError("extension keys must be namespaced")
        self._request = request
        self._identity = {
            "contract_name": CONTRACT_NAME,
            "contract_version": contract_version,
            "package_id": package_id,
            "request_id": request.request_id,
            "run_id": run_id,
            "created_at": created_at,
            "adapter": adapter.as_dict(),
            "boundary": dict(boundary),
            "required_capabilities": sorted(set(required_capabilities)),
            "request_path": "request.json",
        }
        self._extensions = dict(extensions or {})
        self._items: dict[str, PackageItem] = {}
        self._artifacts: dict[str, Artifact] = {}
        self._sealed = False

    def add_item(self, item: PackageItem) -> None:
        if self._sealed:
            raise RuntimeError("package builder is sealed")
        if not item.item_id or "/" in item.item_id or "\\" in item.item_id:
            raise ValueError("item_id must be a non-empty path segment")
        if item.item_id in self._items:
            raise ValueError(f"duplicate item_id: {item.item_id}")
        item.as_dict()
        self._items[item.item_id] = item

    def add_artifact(self, artifact: Artifact) -> None:
        if self._sealed:
            raise RuntimeError("package builder is sealed")
        if not _safe_path(artifact.path) or artifact.path in {
            "package.json",
            "package.sha256",
            "request.json",
        }:
            raise ValueError(f"unsafe or reserved artifact path: {artifact.path}")
        if artifact.path in self._artifacts:
            raise ValueError(f"duplicate artifact path: {artifact.path}")
        self._artifacts[artifact.path] = artifact

    def seal(self, destination: Path) -> SealResult:
        if self._sealed:
            return SealResult(False, error="package builder is already sealed")
        if destination.exists():
            return SealResult(False, error="destination already exists")

        artifacts = dict(self._artifacts)
        artifacts["request.json"] = Artifact(
            "request.json",
            canonical_json_bytes(self._request.as_dict()),
            "acquisition-request",
            "application/json",
        )
        item_paths: list[str] = []
        try:
            for item_id, item in sorted(self._items.items()):
                path = f"items/{item_id}.json"
                item_paths.append(path)
                artifacts[path] = Artifact(
                    path, canonical_json_bytes(item.as_dict()), "item-record", "application/json"
                )
        except (TypeError, ValueError) as exc:
            return SealResult(False, error=f"failed to build package: {_bounded(exc)}")

        outcomes = {outcome.value: 0 for outcome in ItemOutcome}
        for item in self._items.values():
            outcomes[item.outcome.value] += 1
        status = (
            "completed_with_errors" if outcomes["failed"] or outcomes["cancelled"] else "completed"
        )
        inventory = [
            ArtifactInventoryEntry(
                path, value.role, value.media_type, len(value.data), _digest(value.data)
            )
            for path, value in sorted(artifacts.items())
        ]
        manifest: dict[str, Any] = {
            **self._identity,
            "status": status,
            "counts": outcomes,
            "items": item_paths,
            "artifacts": [entry.as_dict() for entry in inventory],
        }
        if self._extensions:
            manifest["extensions"] = self._extensions
        manifest_bytes = canonical_json_bytes(manifest)
        content_address = _digest(manifest_bytes)
        temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
        try:
            temporary.mkdir(parents=True)
            for path, artifact in sorted(artifacts.items()):
                output = temporary.joinpath(*PurePosixPath(path).parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(artifact.data)
            (temporary / "package.json").write_bytes(manifest_bytes)
            (temporary / "package.sha256").write_bytes(f"{content_address}\n".encode())
            temporary.rename(destination)
        except OSError as exc:
            shutil.rmtree(temporary, ignore_errors=True)
            return SealResult(False, error=f"failed to seal package: {_bounded(exc)}")
        self._sealed = True
        return SealResult(True, destination, content_address)


def verify_package(
    package: Path,
    *,
    profile: ConsumerProfile | None = None,
    supported_major_versions: Sequence[int] | None = None,
    supported_capabilities: Sequence[str] | None = None,
    max_manifest_bytes: int | None = None,
    max_sidecar_bytes: int | None = None,
    max_json_depth: int | None = None,
) -> VerificationResult:
    """Verify a sealed package in contract order without exposing untrusted content."""
    if profile is not None and any(
        value is not None
        for value in (
            supported_major_versions,
            supported_capabilities,
            max_manifest_bytes,
            max_sidecar_bytes,
            max_json_depth,
        )
    ):
        raise ValueError("profile cannot be combined with legacy verifier limit arguments")
    effective = profile or ConsumerProfile(
        supported_major_versions=tuple(supported_major_versions or (1,)),
        supported_capabilities=tuple(supported_capabilities or ()),
        max_manifest_bytes=max_manifest_bytes or 4 * 1024 * 1024,
        max_sidecar_bytes=max_sidecar_bytes or 65,
        max_json_depth=max_json_depth or 64,
    )
    supported_major_versions = effective.supported_major_versions
    supported_capabilities = effective.supported_capabilities
    max_manifest_bytes = effective.max_manifest_bytes
    max_sidecar_bytes = effective.max_sidecar_bytes
    max_json_depth = effective.max_json_depth

    def _result(
        state: VerificationState,
        stage: VerificationStage,
        findings: Sequence[VerificationFinding] = (),
        content_address: str | None = None,
        claims: VerifiedManifestClaims | None = None,
        _ignored_profile: ConsumerProfile | None = None,
    ) -> VerificationResult:
        return _make_result(
            state,
            stage,
            findings,
            content_address,
            claims,
            effective,
        )

    manifest_path, sidecar_path = package / "package.json", package / "package.sha256"
    for path in (manifest_path, sidecar_path):
        if not path.is_file() or path.is_symlink():
            return _result(
                VerificationState.REJECTED,
                VerificationStage.ENVELOPE,
                (
                    _finding(
                        "missing-required-file",
                        VerificationStage.ENVELOPE,
                        "required regular file missing",
                        path.name,
                    ),
                ),
            )
    try:
        manifest_size, sidecar_size = manifest_path.stat().st_size, sidecar_path.stat().st_size
        if manifest_size > max_manifest_bytes or sidecar_size > max_sidecar_bytes:
            return _result(
                VerificationState.REJECTED,
                VerificationStage.ENVELOPE,
                (
                    _finding(
                        "consumer-size-limit",
                        VerificationStage.ENVELOPE,
                        "manifest or sidecar exceeds consumer limit",
                        observed=max(manifest_size, sidecar_size),
                    ),
                ),
            )
        sidecar = _bounded_stable_read(sidecar_path, max_sidecar_bytes)
        if not SIDECAR_RE.fullmatch(sidecar):
            return _result(
                VerificationState.REJECTED,
                VerificationStage.SIDECAR_FORMAT,
                (
                    _finding(
                        "invalid-sidecar-format",
                        VerificationStage.SIDECAR_FORMAT,
                        "package.sha256 must be lowercase hexadecimal plus one newline",
                        "package.sha256",
                    ),
                ),
            )
        manifest_bytes = _bounded_stable_read(manifest_path, max_manifest_bytes)
    except OSError:
        return _result(
            VerificationState.INDETERMINATE_IO,
            VerificationStage.ENVELOPE,
            (
                _finding(
                    "io-read-failure", VerificationStage.ENVELOPE, "could not read package envelope"
                ),
            ),
        )
    actual = _digest(manifest_bytes)
    expected = sidecar[:-1].decode()
    if actual != expected:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.MANIFEST_DIGEST,
            (
                _finding(
                    "manifest-digest-mismatch",
                    VerificationStage.MANIFEST_DIGEST,
                    "package.json digest mismatch",
                    "package.json",
                ),
            ),
        )
    try:
        manifest = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
    except _DuplicateKey:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.MANIFEST_PARSE,
            (
                _finding(
                    "duplicate-json-key",
                    VerificationStage.MANIFEST_PARSE,
                    "manifest contains a duplicate object key",
                    "package.json",
                ),
            ),
            actual,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _result(
            VerificationState.REJECTED,
            VerificationStage.MANIFEST_PARSE,
            (
                _finding(
                    "invalid-manifest-json",
                    VerificationStage.MANIFEST_PARSE,
                    "manifest is not valid UTF-8 JSON",
                    "package.json",
                ),
            ),
            actual,
        )
    if max_json_depth is not None and _json_depth(manifest) > max_json_depth:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.MANIFEST_PARSE,
            (
                _finding(
                    "consumer-depth-limit",
                    VerificationStage.MANIFEST_PARSE,
                    "manifest exceeds consumer nesting limit",
                    observed=_json_depth(manifest),
                    expected=max_json_depth,
                ),
            ),
            actual,
        )
    if not isinstance(manifest, dict):
        return _result(
            VerificationState.REJECTED,
            VerificationStage.MANIFEST_PARSE,
            (
                _finding(
                    "invalid-manifest-shape",
                    VerificationStage.MANIFEST_PARSE,
                    "manifest must be an object",
                    "package.json",
                ),
            ),
            actual,
        )

    issues: list[VerificationFinding] = []
    if manifest.get("contract_name") != CONTRACT_NAME:
        issues.append(
            _finding(
                "unsupported-contract-name",
                VerificationStage.COMPATIBILITY,
                "unsupported contract name",
                "contract_name",
            )
        )
    version_value = manifest.get("contract_version")
    try:
        major = int(version_value.split(".", 1)[0]) if isinstance(version_value, str) else -1
    except ValueError:
        major = -1
    if major not in supported_major_versions:
        issues.append(
            _finding(
                "unsupported-contract-major",
                VerificationStage.COMPATIBILITY,
                "unsupported contract major version",
                "contract_version",
            )
        )
    required = manifest.get("required_capabilities", [])
    if not isinstance(required, list) or any(not isinstance(value, str) for value in required):
        issues.append(
            _finding(
                "invalid-required-capabilities",
                VerificationStage.COMPATIBILITY,
                "required_capabilities must be strings",
                "required_capabilities",
            )
        )
    else:
        unsupported = sorted(set(required) - set(supported_capabilities))
        if unsupported:
            issues.append(
                _finding(
                    "unknown-required-capability",
                    VerificationStage.COMPATIBILITY,
                    "unsupported required capability",
                    "required_capabilities",
                )
            )
    if issues:
        return _result(
            VerificationState.REJECTED, VerificationStage.COMPATIBILITY, issues, actual
        )
    compatibility_claims = _curated_claims(manifest, actual)

    inventory = manifest.get("artifacts")
    if not isinstance(inventory, list):
        return _result(
            VerificationState.REJECTED,
            VerificationStage.PATH_SAFETY,
            (
                _finding(
                    "invalid-inventory-shape",
                    VerificationStage.PATH_SAFETY,
                    "artifacts must be a list",
                    "artifacts",
                ),
            ),
            actual,
            compatibility_claims,
        )
    expected_paths: set[str] = set()
    entries: dict[str, Mapping[str, Any]] = {}
    for entry in inventory:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            issues.append(
                _finding(
                    "invalid-inventory-entry",
                    VerificationStage.PATH_SAFETY,
                    "inventory entry requires a string path",
                    "artifacts",
                )
            )
            continue
        relative = entry["path"]
        if (
            not isinstance(entry.get("role"), str)
            or not entry["role"]
            or len(entry["role"]) > 200
            or not isinstance(entry.get("media_type"), str)
            or not entry["media_type"]
            or len(entry["media_type"]) > 200
        ):
            issues.append(
                _finding(
                    "invalid-inventory-metadata",
                    VerificationStage.PATH_SAFETY,
                    "inventory role and media type must be bounded non-empty strings",
                    _bounded(relative),
                )
            )
            continue
        if (
            not _safe_path(relative)
            or relative in expected_paths
            or relative in {"package.json", "package.sha256"}
        ):
            issues.append(
                _finding(
                    "unsafe-artifact-path",
                    VerificationStage.PATH_SAFETY,
                    "unsafe, duplicate, aliased, or reserved path",
                    _bounded(relative),
                )
            )
            continue
        expected_paths.add(relative)
        entries[relative] = entry
    if issues:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.PATH_SAFETY,
            issues,
            actual,
            compatibility_claims,
        )

    actual_paths: set[str] = set()
    folded_paths: set[str] = set()
    aggregate_bytes = 0
    try:
        pending_directories = [package]
        observed_entries = 0
        while pending_directories:
            directory = pending_directories.pop()
            children: list[Path] = []
            for path in directory.iterdir():
                observed_entries += 1
                if observed_entries > effective.max_package_entries:
                    issues.append(
                        _finding(
                            "consumer-entry-limit",
                            VerificationStage.INVENTORY_COVERAGE,
                            "package entry count exceeds consumer limit",
                            observed=observed_entries,
                            expected=effective.max_package_entries,
                        )
                    )
                    pending_directories.clear()
                    children.clear()
                    break
                children.append(path)
            for path in sorted(children, key=lambda value: value.name):
                relative = path.relative_to(package).as_posix()
                components = PurePosixPath(relative).parts
                metadata = path.lstat()
                if stat.S_ISDIR(metadata.st_mode) and not path.is_symlink():
                    if (
                        len(relative) > effective.max_path_length
                        or len(components) > effective.max_path_components
                    ):
                        issues.append(
                            _finding(
                                "consumer-path-limit",
                                VerificationStage.INVENTORY_COVERAGE,
                                "package directory exceeds consumer path limit",
                                relative[:200],
                            )
                        )
                    else:
                        pending_directories.append(path)
                    continue
                if path.is_symlink():
                    issues.append(
                        _finding(
                            "symbolic-link-forbidden",
                            VerificationStage.INVENTORY_COVERAGE,
                            "symbolic links are forbidden",
                            relative,
                        )
                    )
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    issues.append(
                        _finding(
                            "special-file-forbidden",
                            VerificationStage.INVENTORY_COVERAGE,
                            "package entries must be regular files",
                            relative,
                        )
                    )
                    continue
                folded = relative.casefold()
                if (
                    len(relative) > effective.max_path_length
                    or len(components) > effective.max_path_components
                ):
                    issues.append(
                        _finding(
                            "consumer-path-limit",
                            VerificationStage.INVENTORY_COVERAGE,
                            "package path exceeds consumer limit",
                            relative[:200],
                        )
                    )
                if folded in folded_paths:
                    issues.append(
                        _finding(
                            "case-colliding-path",
                            VerificationStage.INVENTORY_COVERAGE,
                            "package paths collide under case folding",
                            relative[:200],
                        )
                    )
                folded_paths.add(folded)
                if metadata.st_nlink > 1:
                    issues.append(
                        _finding(
                            "hard-link-forbidden",
                            VerificationStage.INVENTORY_COVERAGE,
                            "hard-linked package entries are forbidden",
                            relative[:200],
                        )
                    )
                if metadata.st_size > effective.max_file_bytes:
                    issues.append(
                        _finding(
                            "consumer-file-size-limit",
                            VerificationStage.INVENTORY_COVERAGE,
                            "package entry exceeds consumer byte limit",
                            relative[:200],
                            metadata.st_size,
                            effective.max_file_bytes,
                        )
                    )
                aggregate_bytes += metadata.st_size
                actual_paths.add(relative)
    except OSError:
        return _result(
            VerificationState.INDETERMINATE_IO,
            VerificationStage.PATH_SAFETY,
            (
                _finding(
                    "io-scan-failure",
                    VerificationStage.INVENTORY_COVERAGE,
                    "could not enumerate package files",
                ),
            ),
            actual,
            compatibility_claims,
        )
    if len(actual_paths) > effective.max_package_entries:
        issues.append(
            _finding(
                "consumer-entry-limit",
                VerificationStage.INVENTORY_COVERAGE,
                "package entry count exceeds consumer limit",
                observed=len(actual_paths),
                expected=effective.max_package_entries,
            )
        )
    if aggregate_bytes > effective.max_aggregate_bytes:
        issues.append(
            _finding(
                "consumer-aggregate-size-limit",
                VerificationStage.INVENTORY_COVERAGE,
                "package bytes exceed consumer aggregate limit",
                observed=aggregate_bytes,
                expected=effective.max_aggregate_bytes,
            )
        )
    if len(inventory) > effective.max_artifacts:
        issues.append(
            _finding(
                "consumer-artifact-limit",
                VerificationStage.INVENTORY_COVERAGE,
                "artifact inventory exceeds consumer limit",
                observed=len(inventory),
                expected=effective.max_artifacts,
            )
        )
    diagnostic_count = sum(
        entry.get("role") == "diagnostic" for entry in inventory if isinstance(entry, dict)
    )
    if diagnostic_count > effective.max_diagnostics:
        issues.append(
            _finding(
                "consumer-diagnostic-limit",
                VerificationStage.INVENTORY_COVERAGE,
                "diagnostic inventory exceeds consumer limit",
                observed=diagnostic_count,
                expected=effective.max_diagnostics,
            )
        )
    if actual_paths - {"package.json", "package.sha256"} != expected_paths:
        issues.append(
            _finding(
                "inventory-coverage-mismatch",
                VerificationStage.INVENTORY_COVERAGE,
                "inventory does not exactly cover handoff artifacts",
            )
        )
    if issues:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.INVENTORY_COVERAGE,
            issues,
            actual,
            compatibility_claims,
        )

    counts = manifest.get("counts")
    item_paths = manifest.get("items")
    terminal_names = {value.value for value in ItemOutcome}
    if isinstance(item_paths, list) and len(item_paths) > effective.max_item_records:
        issues.append(
            _finding(
                "consumer-item-limit",
                VerificationStage.TERMINAL_ACCOUNTING,
                "item record count exceeds consumer limit",
                observed=len(item_paths),
                expected=effective.max_item_records,
            )
        )
    if (
        not isinstance(counts, dict)
        or set(counts) != terminal_names
        or any(type(v) is not int or v < 0 for v in counts.values())
    ):
        issues.append(
            _finding(
                "invalid-terminal-counts",
                VerificationStage.TERMINAL_ACCOUNTING,
                "counts must contain nonnegative integers for every terminal outcome",
                "counts",
            )
        )
    if not isinstance(item_paths, list) or any(
        not isinstance(path, str) or path not in expected_paths for path in item_paths
    ):
        issues.append(
            _finding(
                "invalid-item-references",
                VerificationStage.TERMINAL_ACCOUNTING,
                "item references must be inventoried paths",
                "items",
            )
        )
    if issues:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.TERMINAL_ACCOUNTING,
            issues,
            actual,
            compatibility_claims,
        )

    structural_data: dict[str, bytes] = {}
    observed = {value.value: 0 for value in ItemOutcome}
    parsed_items: list[tuple[str, Mapping[str, Any]]] = []
    assert isinstance(item_paths, list)
    for relative in item_paths:
        try:
            structural_data[relative] = _bounded_stable_read(
                package.joinpath(*PurePosixPath(relative).parts), effective.max_file_bytes
            )
        except OSError:
            return _result(
                VerificationState.INDETERMINATE_IO,
                VerificationStage.TERMINAL_ACCOUNTING,
                (
                    _finding(
                        "io-item-read-failure",
                        VerificationStage.TERMINAL_ACCOUNTING,
                        "could not read inventoried item record",
                        relative,
                    ),
                ),
                actual,
                compatibility_claims,
            )
        try:
            item = json.loads(structural_data[relative], object_pairs_hook=_unique_object)
            if not isinstance(item, dict):
                raise ValueError
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            _DuplicateKey,
            KeyError,
            ValueError,
            TypeError,
        ):
            issues.append(
                _finding(
                    "invalid-item-record",
                    VerificationStage.ITEM_SEMANTICS,
                    "invalid item record",
                    relative,
                )
            )
            continue
        try:
            outcome = ItemOutcome(item["outcome"])
        except (KeyError, ValueError, TypeError):
            issues.append(
                _finding(
                    "nonterminal-item-outcome",
                    VerificationStage.TERMINAL_ACCOUNTING,
                    "sealed item must use a terminal outcome",
                    relative,
                )
            )
            continue
        observed[outcome.value] += 1
        parsed_items.append((relative, item))
    if counts != observed:
        issues.append(
            _finding(
                "terminal-count-mismatch",
                VerificationStage.TERMINAL_ACCOUNTING,
                "manifest counts do not match item outcomes",
                "counts",
            )
        )
    wanted = "completed_with_errors" if observed["failed"] or observed["cancelled"] else "completed"
    if manifest.get("status") != wanted:
        issues.append(
            _finding(
                "status-outcome-mismatch",
                VerificationStage.TERMINAL_ACCOUNTING,
                "package status does not match terminal outcomes",
                "status",
            )
        )
    if issues:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.TERMINAL_ACCOUNTING,
            issues,
            actual,
            compatibility_claims,
        )

    accounting_claims = _curated_claims(manifest, actual, accounting=True)

    claimed_references: dict[str, str] = {}
    for relative, item in parsed_items:
        outcome = ItemOutcome(item["outcome"])
        error = item.get("error")
        if (
            not isinstance(item.get("item_id"), str)
            or not item["item_id"]
            or len(item["item_id"]) > 200
            or not isinstance(item.get("resource_kind"), str)
            or not item["resource_kind"]
            or len(item["resource_kind"]) > 200
        ):
            issues.append(
                _finding(
                    "invalid-item-identity",
                    VerificationStage.ITEM_SEMANTICS,
                    "item identity fields must be bounded non-empty strings",
                    relative,
                )
            )
        for field_name in ("requested_locator", "resolved_locator", "canonical_locator"):
            locator = item.get(field_name)
            if locator is not None and (not isinstance(locator, str) or len(locator) > 2048):
                issues.append(
                    _finding(
                        "invalid-item-locator",
                        VerificationStage.ITEM_SEMANTICS,
                        "item locators must be bounded strings",
                        relative,
                    )
                )
        for field_name, diagnostic_role in (("artifacts", False), ("diagnostics", True)):
            references = item.get(field_name, [])
            if not isinstance(references, list) or len(references) > 256 or any(
                not isinstance(reference, str) for reference in references
            ):
                issues.append(
                    _finding(
                        "invalid-item-artifact-references",
                        VerificationStage.ITEM_SEMANTICS,
                        "item artifact and diagnostic references must be bounded string lists",
                        relative,
                    )
                )
                continue
            for reference in references:
                entry = entries.get(reference)
                if entry is None or (entry.get("role") == "diagnostic") is not diagnostic_role:
                    issues.append(
                        _finding(
                            "invalid-item-artifact-reference",
                            VerificationStage.ITEM_SEMANTICS,
                            "item reference is missing or has the wrong artifact role",
                            relative,
                        )
                    )
                    continue
                owner = claimed_references.get(reference)
                if owner is not None and owner != relative:
                    issues.append(
                        _finding(
                            "cross-item-artifact-reference",
                            VerificationStage.ITEM_SEMANTICS,
                            "artifact reference is claimed by more than one item",
                            reference,
                        )
                    )
                claimed_references[reference] = relative
        if outcome in {ItemOutcome.COMPLETED, ItemOutcome.UNCHANGED} and error is not None:
            issues.append(
                _finding(
                    "contradictory-item-error",
                    VerificationStage.ITEM_SEMANTICS,
                    "successful item outcome cannot carry an error",
                    relative,
                )
            )
        if outcome in {ItemOutcome.FAILED, ItemOutcome.CANCELLED} and not isinstance(error, dict):
            issues.append(
                _finding(
                    "missing-item-error",
                    VerificationStage.ITEM_SEMANTICS,
                    "failed or cancelled item requires a structured error",
                    relative,
                )
            )
        if outcome is ItemOutcome.SKIPPED and not isinstance(item.get("skip_reason"), (str, dict)):
            issues.append(
                _finding(
                    "missing-skip-reason",
                    VerificationStage.ITEM_SEMANTICS,
                    "skipped item requires a skip_reason",
                    relative,
                )
            )
    if issues:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.ITEM_SEMANTICS,
            issues,
            actual,
            accounting_claims,
        )

    receipt_path = manifest.get("run_receipt")
    if receipt_path is not None:
        if not isinstance(receipt_path, str) or receipt_path not in expected_paths:
            issues.append(
                _finding(
                    "invalid-run-receipt-reference",
                    VerificationStage.LINEAGE,
                    "run receipt must reference an inventoried artifact",
                    "run_receipt",
                )
            )
        else:
            try:
                structural_data[receipt_path] = _bounded_stable_read(
                    package.joinpath(*PurePosixPath(receipt_path).parts),
                    effective.max_file_bytes,
                )
            except OSError:
                return _result(
                    VerificationState.INDETERMINATE_IO,
                    VerificationStage.LINEAGE,
                    (
                        _finding(
                            "io-run-receipt-read-failure",
                            VerificationStage.LINEAGE,
                            "could not read inventoried run receipt",
                            receipt_path,
                        ),
                    ),
                    actual,
                    accounting_claims,
                )
            try:
                receipt = json.loads(
                    structural_data[receipt_path], object_pairs_hook=_unique_object
                )
            except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey):
                receipt = None
                issues.append(
                    _finding(
                        "invalid-run-receipt",
                        VerificationStage.LINEAGE,
                        "run receipt is not valid UTF-8 JSON",
                        receipt_path,
                    )
                )
            if isinstance(receipt, dict):
                lineage_keys = {
                    "run_id",
                    "resumes_run_id",
                    "prior_run_ids",
                    "prior_package_ids",
                    "reconciliation_summary",
                    "final_attempt_counts",
                }
                for key in lineage_keys & receipt.keys():
                    if key in manifest and receipt[key] != manifest[key]:
                        issues.append(
                            _finding(
                                "receipt-lineage-conflict",
                                VerificationStage.LINEAGE,
                                "run receipt conflicts with authoritative manifest lineage",
                                key,
                            )
                        )
    if issues:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.LINEAGE,
            issues,
            actual,
            accounting_claims,
        )

    lineage_claims = _curated_claims(manifest, actual, accounting=True, lineage=True)
    for relative in sorted(expected_paths):
        try:
            data = _bounded_stable_read(
                package.joinpath(*PurePosixPath(relative).parts), effective.max_file_bytes
            )
        except OSError:
            return _result(
                VerificationState.INDETERMINATE_IO,
                VerificationStage.ARTIFACT_INTEGRITY,
                (
                    _finding(
                        "io-artifact-read-failure",
                        VerificationStage.ARTIFACT_INTEGRITY,
                        "could not read inventoried artifact",
                        relative,
                    ),
                ),
                actual,
                lineage_claims,
            )
        entry = entries[relative]
        if type(entry.get("bytes")) is not int or entry["bytes"] != len(data):
            issues.append(
                _finding(
                    "artifact-size-mismatch",
                    VerificationStage.ARTIFACT_INTEGRITY,
                    "artifact byte size mismatch",
                    relative,
                    len(data),
                    entry.get("bytes"),
                )
            )
        digest = entry.get("sha256")
        if (
            not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
            or digest != _digest(data)
        ):
            issues.append(
                _finding(
                    "artifact-digest-mismatch",
                    VerificationStage.ARTIFACT_INTEGRITY,
                    "artifact SHA-256 mismatch",
                    relative,
                )
            )
    if issues:
        return _result(
            VerificationState.REJECTED,
            VerificationStage.ARTIFACT_INTEGRITY,
            issues,
            actual,
            lineage_claims,
        )
    verified_artifacts = tuple(
        VerifiedArtifactClaim(
            path,
            _bounded_claim(entry.get("role")) or "",
            _bounded_claim(entry.get("media_type")) or "",
            entry["bytes"],
            entry["sha256"],
        )
        for path, entry in sorted(entries.items())
    )
    verified_items = _verified_item_dispositions(
        parsed_items, {artifact.path: artifact for artifact in verified_artifacts}
    )
    totals = VerifiedPackageTotals(
        package_entries=len(actual_paths),
        item_records=len(parsed_items),
        artifacts=len(inventory),
        diagnostics=diagnostic_count,
        aggregate_bytes=aggregate_bytes,
    )
    complete_claims = _curated_claims(
        manifest,
        actual,
        accounting=True,
        lineage=True,
        item_dispositions=verified_items,
        artifact_inventory=verified_artifacts,
        totals=totals,
    )
    return _result(
        VerificationState.VERIFIED,
        VerificationStage.COMPLETE,
        (),
        actual,
        complete_claims,
        effective,
    )
