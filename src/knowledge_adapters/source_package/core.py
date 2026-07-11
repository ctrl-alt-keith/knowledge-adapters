"""Deterministic Source Package assembly, sealing, and verification."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
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

CONTRACT_NAME = "knowledge-source-package"
RESULT_SCHEMA_VERSION = "2.0.0"
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

    schema_version: str = "1.0.0"
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


def _result(
    state: VerificationState,
    stage: VerificationStage,
    findings: Sequence[VerificationFinding] = (),
    content_address: str | None = None,
    claims: VerifiedManifestClaims | None = None,
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
    )


def _bounded_claim(value: object, limit: int = 200) -> str | None:
    return value if isinstance(value, str) and len(value) <= limit else None


def _bounded_string_tuple(value: object, *, limit: int = 256) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        return ()
    if any(not isinstance(item, str) or len(item) > 200 for item in value):
        return ()
    return tuple(value)


def _curated_claims(
    manifest: Mapping[str, Any],
    content_address: str,
    *,
    accounting: bool = False,
    lineage: bool = False,
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
    supported_major_versions: Sequence[int] = (1,),
    supported_capabilities: Sequence[str] = (),
    max_manifest_bytes: int = 4 * 1024 * 1024,
    max_sidecar_bytes: int = 65,
    max_json_depth: int | None = None,
) -> VerificationResult:
    """Verify a sealed package in contract order without exposing untrusted content."""
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
        sidecar = sidecar_path.read_bytes()
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
        manifest_bytes = manifest_path.read_bytes()
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
    try:
        for path in package.rglob("*"):
            relative = path.relative_to(package).as_posix()
            if path.is_symlink():
                issues.append(
                    _finding(
                        "symbolic-link-forbidden",
                        VerificationStage.INVENTORY_COVERAGE,
                        "symbolic links are forbidden",
                        relative,
                    )
                )
            elif path.is_file():
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
            structural_data[relative] = package.joinpath(
                *PurePosixPath(relative).parts
            ).read_bytes()
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

    for relative, item in parsed_items:
        outcome = ItemOutcome(item["outcome"])
        error = item.get("error")
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
                structural_data[receipt_path] = package.joinpath(
                    *PurePosixPath(receipt_path).parts
                ).read_bytes()
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
            data = package.joinpath(*PurePosixPath(relative).parts).read_bytes()
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
    return _result(
        VerificationState.VERIFIED,
        VerificationStage.COMPLETE,
        (),
        actual,
        lineage_claims,
    )
