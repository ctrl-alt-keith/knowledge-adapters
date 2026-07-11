"""Implementation-neutral source-package conformance fixture materializer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _base_package() -> tuple[dict[str, Any], dict[str, bytes]]:
    request = _json_bytes(
        {
            "adapter_type": "document",
            "output_location": "source-package",
            "request_id": "request-001",
            "scope": {"kind": "resource"},
            "targets": ["https://example.test/document/1"],
        }
    )
    item = _json_bytes(
        {
            "acquired_at": "2026-07-10T00:00:00Z",
            "artifacts": [],
            "canonical_locator": "https://example.test/document/1",
            "item_id": "item-001",
            "outcome": "completed",
            "provenance": {"provider": "fixture", "provider_resource_id": "1"},
            "resource_kind": "document",
        }
    )
    files = {"request.json": request, "items/item-001.json": item}
    manifest: dict[str, Any] = {
        "adapter": {"name": "fixture-adapter", "version": "1.0.0"},
        "artifacts": [
            {
                "bytes": len(content),
                "media_type": "application/json",
                "path": path,
                "role": "request" if path == "request.json" else "item-record",
                "sha256": _digest(content),
            }
            for path, content in files.items()
        ],
        "boundary": {"deterministic": "fixture assembly", "live": "none"},
        "contract_name": "knowledge-source-package",
        "contract_version": "1.0.0",
        "counts": {"cancelled": 0, "completed": 1, "failed": 0, "skipped": 0, "unchanged": 0},
        "created_at": "2026-07-10T00:00:00Z",
        "items": ["items/item-001.json"],
        "package_id": "package-001",
        "request_id": "request-001",
        "request_path": "request.json",
        "required_capabilities": [],
        "run_id": "run-001",
        "status": "completed",
    }
    return manifest, files


def materialize_vector(root: Path, mutation: str) -> Path:
    """Write one deterministic vector and return its package directory."""
    package = root / mutation
    manifest, files = _base_package()

    if mutation == "completed_with_errors":
        failed = json.loads(files["items/item-001.json"])
        failed["outcome"] = "failed"
        failed["error"] = {"attempts": 2, "category": "provider-unavailable", "retryable": True}
        files["items/item-001.json"] = _json_bytes(failed)
        manifest["status"] = "completed_with_errors"
        manifest["counts"]["completed"] = 0
        manifest["counts"]["failed"] = 1
    elif mutation in {
        "progress_exhausted",
        "progress_continuation",
        "progress_resumed",
        "progress_invalid",
        "progress_invalid_resume",
        "progress_missing_capability",
        "progress_resume_mismatched_prior",
        "progress_resume_missing_attempts",
        "progress_resume_missing_prior",
        "progress_resume_missing_summary",
        "progress_resume_self",
        "progress_resume_self_package",
        "progress_wrong_version",
    }:
        if mutation != "progress_wrong_version":
            manifest["contract_version"] = "1.1.0"
        if mutation != "progress_missing_capability":
            manifest["required_capabilities"] = ["collection-progress"]
        state = "continuation_remaining" if mutation in {
            "progress_continuation",
            "progress_resumed",
        } else "exhausted"
        manifest["collection_progress"] = {"state": state}
        if mutation == "progress_resumed":
            manifest["resumes_run_id"] = "run-000"
            manifest["prior_run_ids"] = ["run-000"]
            manifest["prior_package_ids"] = ["package-000"]
            manifest["reconciliation_summary"] = {"reused": 1}
            manifest["final_attempt_counts"] = {"item-001": 2}
        elif mutation == "progress_invalid":
            manifest["collection_progress"]["unexpected"] = True
        elif mutation == "progress_invalid_resume":
            manifest["resumes_run_id"] = 7
        elif mutation.startswith("progress_resume_"):
            manifest["collection_progress"] = {"state": "continuation_remaining"}
            manifest["resumes_run_id"] = "run-000"
            manifest["prior_run_ids"] = ["run-000"]
            manifest["reconciliation_summary"] = {"reused": 0}
            manifest["final_attempt_counts"] = {}
            if mutation == "progress_resume_mismatched_prior":
                manifest["prior_run_ids"] = ["run-other"]
            elif mutation == "progress_resume_missing_attempts":
                manifest.pop("final_attempt_counts")
            elif mutation == "progress_resume_missing_prior":
                manifest.pop("prior_run_ids")
            elif mutation == "progress_resume_missing_summary":
                manifest.pop("reconciliation_summary")
            elif mutation == "progress_resume_self":
                manifest["resumes_run_id"] = "run-001"
                manifest["prior_run_ids"] = ["run-001"]
            elif mutation == "progress_resume_self_package":
                manifest["prior_package_ids"] = ["package-001"]
    elif mutation in {"sealed_receipt", "receipt_override", "compound_lineage_artifact"}:
        receipt_run = (
            "run-other"
            if mutation in {"receipt_override", "compound_lineage_artifact"}
            else "run-001"
        )
        files["run-receipt.json"] = _json_bytes({"receipt_version": "1.0.0", "run_id": receipt_run})
        manifest["run_receipt"] = "run-receipt.json"
    elif mutation == "path_duplicate":
        manifest["artifacts"].append(dict(manifest["artifacts"][0]))
    elif mutation == "path_absolute":
        manifest["artifacts"][0]["path"] = "/request.json"
    elif mutation == "path_escape":
        manifest["artifacts"][0]["path"] = "../request.json"
    elif mutation == "version_unsupported_major":
        manifest["contract_version"] = "2.0.0"
    elif mutation == "capability_unknown_required":
        manifest["required_capabilities"] = ["example.test/unknown"]
    elif mutation == "counts_inconsistent":
        manifest["counts"]["completed"] = 2
    elif mutation == "item_nonterminal":
        item = json.loads(files["items/item-001.json"])
        item["outcome"] = "in_progress"
        files["items/item-001.json"] = _json_bytes(item)
    elif mutation == "completed_with_error":
        item = json.loads(files["items/item-001.json"])
        item["error"] = {"attempts": 1, "category": "contradiction", "retryable": False}
        files["items/item-001.json"] = _json_bytes(item)
    elif mutation == "compound_accounting_artifact":
        manifest["counts"]["completed"] = 2
    elif mutation == "compound_semantics_artifact":
        item = json.loads(files["items/item-001.json"])
        item["error"] = {"attempts": 1, "category": "contradiction", "retryable": False}
        files["items/item-001.json"] = _json_bytes(item)
    elif mutation == "manifest_oversized":
        manifest["extensions"] = {"example.test/padding": "x" * 5000}
    elif mutation == "manifest_excessive_nesting":
        nested: object = "leaf"
        for _ in range(17):
            nested = {"nested": nested}
        manifest["extensions"] = {"example.test/deep": nested}

    for entry in manifest["artifacts"]:
        path = entry["path"]
        if path in files:
            entry["bytes"] = len(files[path])
            entry["sha256"] = _digest(files[path])
    if mutation in {"sealed_receipt", "receipt_override", "compound_lineage_artifact"}:
        content = files["run-receipt.json"]
        manifest["artifacts"].append(
            {
                "bytes": len(content),
                "media_type": "application/json",
                "path": "run-receipt.json",
                "role": "run-receipt",
                "sha256": _digest(content),
            }
        )
    if mutation in {
        "compound_accounting_artifact",
        "compound_semantics_artifact",
        "compound_lineage_artifact",
    }:
        manifest["artifacts"][0]["sha256"] = "0" * 64

    manifest_bytes = _json_bytes(manifest)
    sidecar = (_digest(manifest_bytes) + "\n").encode()

    if mutation == "sidecar_malformed":
        sidecar = b"not-a-digest\n"
    elif mutation == "sidecar_uppercase":
        sidecar = sidecar.upper()
    elif mutation == "sidecar_no_newline":
        sidecar = sidecar.rstrip(b"\n")
    elif mutation == "sidecar_mismatch":
        sidecar = ("0" * 64 + "\n").encode()
    elif mutation == "manifest_modified":
        manifest_bytes += b" "
    elif mutation == "manifest_invalid_utf8":
        manifest_bytes = b"\xff"
        sidecar = (_digest(manifest_bytes) + "\n").encode()
    elif mutation == "manifest_invalid_json":
        manifest_bytes = b"{\n"
        sidecar = (_digest(manifest_bytes) + "\n").encode()
    elif mutation == "manifest_duplicate_key":
        manifest_bytes = manifest_bytes.replace(
            b'{\n  "adapter":', b'{\n  "run_id": "duplicate",\n  "adapter":', 1
        )
        sidecar = (_digest(manifest_bytes) + "\n").encode()
    elif mutation == "artifact_digest_mismatch":
        manifest["artifacts"][0]["sha256"] = "0" * 64
        manifest_bytes = _json_bytes(manifest)
        sidecar = (_digest(manifest_bytes) + "\n").encode()
    elif mutation == "artifact_size_mismatch":
        manifest["artifacts"][0]["bytes"] += 1
        manifest_bytes = _json_bytes(manifest)
        sidecar = (_digest(manifest_bytes) + "\n").encode()
    elif mutation == "artifact_missing":
        files.pop("request.json")
    elif mutation == "artifact_undeclared":
        files["diagnostics/undeclared.json"] = b"{}\n"

    package.mkdir(parents=True)
    (package / "package.json").write_bytes(manifest_bytes)
    (package / "package.sha256").write_bytes(sidecar)
    for path, content in files.items():
        destination = package / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return package
