"""Deterministic Source Package assembly, sealing, and verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .models import AdapterIdentity, Artifact, ArtifactInventoryEntry, ItemOutcome, PackageItem

CONTRACT_NAME = "knowledge-source-package"
SIDECAR_RE = re.compile(rb"[0-9a-f]{64}\n\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON deterministically as UTF-8, with one trailing newline."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _safe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and "\\" not in value and not path.is_absolute() and ".." not in path.parts


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SealResult:
    ok: bool
    package_path: Path | None = None
    content_address: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    issues: tuple[VerificationIssue, ...]
    content_address: str | None = None
    manifest: Mapping[str, Any] | None = None


class PackageBuilder:
    """Collect a complete package in memory and atomically seal it once."""

    def __init__(
        self,
        *,
        package_id: str,
        request_id: str,
        run_id: str,
        created_at: str,
        adapter: AdapterIdentity,
        contract_version: str = "1.0.0",
        required_capabilities: Sequence[str] = (),
        boundary: Mapping[str, str],
        manifest_fields: Mapping[str, Any] | None = None,
    ) -> None:
        self._identity = {
            "contract_name": CONTRACT_NAME,
            "contract_version": contract_version,
            "package_id": package_id,
            "request_id": request_id,
            "run_id": run_id,
            "created_at": created_at,
            "adapter": adapter.as_dict(),
            "boundary": dict(boundary),
            "required_capabilities": sorted(set(required_capabilities)),
        }
        self._extra = dict(manifest_fields or {})
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
        self._items[item.item_id] = item

    def add_artifact(self, artifact: Artifact) -> None:
        if self._sealed:
            raise RuntimeError("package builder is sealed")
        if not _safe_path(artifact.path) or artifact.path in {"package.json", "package.sha256"}:
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
        item_paths: list[str] = []
        for item_id, item in sorted(self._items.items()):
            path = f"items/{item_id}.json"
            item_paths.append(path)
            artifacts[path] = Artifact(
                path, canonical_json_bytes(item.as_dict()), "item-record", "application/json"
            )

        outcomes = {outcome.value: 0 for outcome in ItemOutcome}
        for item in self._items.values():
            outcomes[item.outcome.value] += 1
        status = (
            "completed_with_errors"
            if outcomes[ItemOutcome.FAILED.value] or outcomes[ItemOutcome.CANCELLED.value]
            else "completed"
        )
        inventory = [
            ArtifactInventoryEntry(
                path, value.role, value.media_type, len(value.data), _digest(value.data)
            )
            for path, value in sorted(artifacts.items())
        ]
        manifest = {
            **self._identity,
            **self._extra,
            "status": status,
            "counts": outcomes,
            "items": item_paths,
            "artifacts": [entry.as_dict() for entry in inventory],
        }
        manifest_bytes = canonical_json_bytes(manifest)
        content_address = _digest(manifest_bytes)
        temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
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
            return SealResult(False, error=f"failed to seal package: {exc}")
        self._sealed = True
        return SealResult(True, destination, content_address)


def verify_package(
    package: Path,
    *,
    supported_major_versions: Sequence[int] = (1,),
    supported_capabilities: Sequence[str] = (),
    max_manifest_bytes: int = 4 * 1024 * 1024,
    max_sidecar_bytes: int = 65,
) -> VerificationResult:
    """Verify a sealed package in the contract-mandated order without raising."""
    manifest_path, sidecar_path = package / "package.json", package / "package.sha256"
    for path in (manifest_path, sidecar_path):
        if not path.is_file() or path.is_symlink():
            return VerificationResult(
                False, (VerificationIssue("missing", "required regular file missing", path.name),)
            )
    try:
        if (
            manifest_path.stat().st_size > max_manifest_bytes
            or sidecar_path.stat().st_size > max_sidecar_bytes
        ):
            return VerificationResult(
                False, (VerificationIssue("size-limit", "manifest or sidecar exceeds size limit"),)
            )
        sidecar = sidecar_path.read_bytes()
        if not SIDECAR_RE.fullmatch(sidecar):
            return VerificationResult(
                False,
                (
                    VerificationIssue(
                        "sidecar-format", "invalid package.sha256 format", "package.sha256"
                    ),
                ),
            )
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        return VerificationResult(False, (VerificationIssue("read-error", str(exc)),))
    actual = _digest(manifest_bytes)
    expected = sidecar[:-1].decode()
    if actual != expected:
        return VerificationResult(
            False,
            (VerificationIssue("manifest-digest", "package.json digest mismatch", "package.json"),),
        )
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return VerificationResult(
            False, (VerificationIssue("manifest-json", str(exc), "package.json"),), actual
        )
    issues: list[VerificationIssue] = []
    if not isinstance(manifest, dict):
        return VerificationResult(
            False, (VerificationIssue("manifest-shape", "manifest must be an object"),), actual
        )
    if manifest.get("contract_name") != CONTRACT_NAME:
        issues.append(VerificationIssue("contract-name", "unsupported contract name"))
    version = manifest.get("contract_version")
    try:
        major = int(version.split(".", 1)[0]) if isinstance(version, str) else -1
    except ValueError:
        major = -1
    if major not in supported_major_versions:
        issues.append(VerificationIssue("contract-version", "unsupported contract major version"))
    required = manifest.get("required_capabilities", [])
    if not isinstance(required, list) or any(not isinstance(value, str) for value in required):
        issues.append(
            VerificationIssue("capabilities-shape", "required_capabilities must be strings")
        )
    else:
        unsupported = sorted(set(required) - set(supported_capabilities))
        if unsupported:
            issues.append(
                VerificationIssue("required-capability", f"unsupported: {', '.join(unsupported)}")
            )
    inventory = manifest.get("artifacts")
    if not isinstance(inventory, list):
        issues.append(VerificationIssue("inventory-shape", "artifacts must be a list"))
        inventory = []
    counts = manifest.get("counts")
    if not isinstance(counts, dict) or set(counts) != {value.value for value in ItemOutcome}:
        issues.append(
            VerificationIssue("accounting", "counts must contain exactly all terminal outcomes")
        )
    expected_paths: set[str] = set()
    for entry in inventory:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            issues.append(VerificationIssue("inventory-entry", "invalid inventory entry"))
            continue
        relative = entry["path"]
        if (
            not _safe_path(relative)
            or relative in expected_paths
            or relative in {"package.json", "package.sha256"}
        ):
            issues.append(
                VerificationIssue("path-safety", "unsafe, duplicate, or reserved path", relative)
            )
            continue
        expected_paths.add(relative)
    if issues:
        return VerificationResult(False, tuple(issues), actual, manifest)
    actual_paths: set[str] = set()
    try:
        for path in package.rglob("*"):
            if path.is_symlink():
                issues.append(
                    VerificationIssue(
                        "path-safety",
                        "symbolic links are forbidden",
                        path.relative_to(package).as_posix(),
                    )
                )
            elif path.is_file():
                actual_paths.add(path.relative_to(package).as_posix())
    except OSError as exc:
        issues.append(VerificationIssue("read-error", str(exc)))
    if actual_paths - {"package.json", "package.sha256"} != expected_paths:
        issues.append(
            VerificationIssue(
                "inventory-coverage", "inventory does not exactly cover handoff artifacts"
            )
        )
    entries = {entry["path"]: entry for entry in inventory}
    for relative in sorted(expected_paths):
        try:
            data = package.joinpath(*PurePosixPath(relative).parts).read_bytes()
        except OSError as exc:
            issues.append(VerificationIssue("artifact-read", str(exc), relative))
            continue
        entry = entries[relative]
        if type(entry.get("bytes")) is not int or entry["bytes"] != len(data):
            issues.append(VerificationIssue("artifact-size", "byte size mismatch", relative))
        digest = entry.get("sha256")
        if (
            not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
            or digest != _digest(data)
        ):
            issues.append(VerificationIssue("artifact-digest", "SHA-256 mismatch", relative))
    item_paths = manifest.get("items")
    if not isinstance(item_paths, list) or any(path not in expected_paths for path in item_paths):
        issues.append(VerificationIssue("items", "item references must be inventoried paths"))
    else:
        observed = {value.value: 0 for value in ItemOutcome}
        for relative in item_paths:
            try:
                item = json.loads(package.joinpath(*PurePosixPath(relative).parts).read_bytes())
                observed[ItemOutcome(item["outcome"]).value] += 1
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ):
                issues.append(VerificationIssue("item-record", "invalid item record", relative))
        if counts != observed:
            issues.append(
                VerificationIssue("accounting", "manifest counts do not match item outcomes")
            )
        wanted = (
            "completed_with_errors" if observed["failed"] or observed["cancelled"] else "completed"
        )
        if manifest.get("status") != wanted:
            issues.append(
                VerificationIssue("accounting", "package status does not match item outcomes")
            )
    return VerificationResult(not issues, tuple(issues), actual, manifest)
