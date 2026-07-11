import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from knowledge_adapters.source_package import (
    AcquisitionRequest,
    AdapterIdentity,
    Artifact,
    ConsumerProfile,
    ItemOutcome,
    PackageBuilder,
    PackageItem,
    verify_package,
)

ORIGINAL_READ_BYTES = Path.read_bytes


def request() -> AcquisitionRequest:
    return AcquisitionRequest(
        request_id="req-1",
        adapter_type="fixture",
        targets=("fixture:one",),
        scope={"kind": "resource"},
        output_location="package",
        selection={"language": "en"},
        extensions={"org.example.fixture": {"mode": "test"}},
    )


def builder() -> PackageBuilder:
    value = PackageBuilder(
        package_id="pkg-1",
        request=request(),
        run_id="run-1",
        created_at="2026-07-10T00:00:00Z",
        adapter=AdapterIdentity("fixture", "1.0.0"),
        boundary={"live": "fixture", "deterministic": "assembly"},
    )
    value.add_item(PackageItem("one", "document", ItemOutcome.COMPLETED))
    return value


def rewrite_manifest(
    destination: Path, mutate: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    manifest = cast(dict[str, Any], json.loads((destination / "package.json").read_bytes()))
    mutate(manifest)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    (destination / "package.json").write_bytes(manifest_bytes)
    (destination / "package.sha256").write_text(
        hashlib.sha256(manifest_bytes).hexdigest() + "\n"
    )
    return manifest


def test_seal_is_deterministic_and_verifiable(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    one, two = builder().seal(first), builder().seal(second)
    assert one.ok and two.ok
    assert one.content_address == two.content_address
    result = verify_package(first)
    assert result.ok
    assert result.content_address == one.content_address
    assert result.state == "verified"
    assert result.last_completed_stage == "complete"
    assert (first / "request.json").read_bytes() == (second / "request.json").read_bytes()
    manifest = json.loads((first / "package.json").read_bytes())
    assert manifest["request_path"] == "request.json"
    request_entry = next(item for item in manifest["artifacts"] if item["path"] == "request.json")
    assert request_entry["role"] == "acquisition-request"


def test_verifier_rejects_manifest_before_parsing(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    (destination / "package.json").write_bytes(b"not json")
    result = verify_package(destination)
    assert not result.ok
    assert result.issues[0].code == "manifest-digest-mismatch"
    assert result.last_completed_stage == "sidecar-format"
    assert result.findings[0].stage == "manifest-digest"
    assert result.verified_claims is None


def test_builder_rejects_unsafe_paths() -> None:
    value = builder()
    try:
        value.add_artifact(Artifact("../escape", b"x", "bad", "text/plain"))
    except ValueError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("unsafe path accepted")


def test_builder_rejects_reserved_manifest_fields_and_request_artifact() -> None:
    try:
        PackageBuilder(
            package_id="pkg-1",
            request=request(),
            run_id="run-1",
            created_at="2026-07-10T00:00:00Z",
            adapter=AdapterIdentity("fixture", "1.0.0"),
            boundary={"live": "fixture", "deterministic": "assembly"},
            manifest_fields={"status": "completed"},
        )
    except ValueError as exc:
        assert "reserved" in str(exc)
    else:
        raise AssertionError("reserved manifest field accepted")
    value = builder()
    try:
        value.add_artifact(Artifact("request.json", b"{}", "request", "application/json"))
    except ValueError as exc:
        assert "reserved" in str(exc)
    else:
        raise AssertionError("caller-provided request artifact accepted")


def test_seal_failure_cleans_temporary_output_and_retry_succeeds(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = builder()
    with patch.object(Path, "rename", side_effect=OSError("simulated rename failure")):
        failed = value.seal(destination)
    assert not failed.ok
    assert not destination.exists()
    assert not list(tmp_path.glob(".package.tmp-*"))
    assert value.seal(destination).ok


def test_verifier_rejects_duplicate_manifest_keys_after_digest(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    manifest = (destination / "package.json").read_bytes()
    duplicate = manifest.replace(b'{"adapter":', b'{"run_id":"other","adapter":', 1)
    (destination / "package.json").write_bytes(duplicate)
    (destination / "package.sha256").write_text(hashlib.sha256(duplicate).hexdigest() + "\n")
    result = verify_package(destination)
    assert result.state == "rejected"
    assert result.last_completed_stage == "manifest-digest"
    assert result.findings[0].stage == "manifest-parse"
    assert result.findings[0].code == "duplicate-json-key"


def test_verifier_applies_consumer_json_depth_limit(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    result = verify_package(destination, max_json_depth=2)
    assert result.state == "rejected"
    assert result.findings[0].code == "consumer-depth-limit"


def test_accounting_precedes_candidate_artifact_integrity(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = builder()
    value.add_artifact(
        Artifact("artifacts/one.md", b"original\n", "normalized-content", "text/markdown")
    )
    assert value.seal(destination).ok
    rewrite_manifest(destination, lambda manifest: manifest["counts"].update(completed=2))
    (destination / "artifacts/one.md").write_bytes(b"corrupt\n")
    result = verify_package(destination)
    assert result.findings[0].stage == "terminal-accounting"
    assert result.last_completed_stage == "inventory-coverage"


def test_item_semantics_precedes_candidate_artifact_integrity(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = builder()
    value.add_artifact(
        Artifact("artifacts/one.md", b"original\n", "normalized-content", "text/markdown")
    )
    assert value.seal(destination).ok
    item_path = destination / "items/one.json"
    item = json.loads(item_path.read_bytes())
    item["error"] = {"category": "contradiction"}
    item_path.write_bytes((json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode())
    (destination / "artifacts/one.md").write_bytes(b"corrupt\n")
    result = verify_package(destination)
    assert result.findings[0].stage == "item-semantics"
    assert result.last_completed_stage == "terminal-accounting"


def test_lineage_precedes_candidate_artifact_integrity(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = builder()
    value.add_artifact(
        Artifact("artifacts/one.md", b"original\n", "normalized-content", "text/markdown")
    )
    value.add_artifact(
        Artifact(
            "run-receipt.json",
            b'{"run_id":"other"}\n',
            "run-receipt",
            "application/json",
        )
    )
    assert value.seal(destination).ok
    rewrite_manifest(destination, lambda manifest: manifest.update(run_receipt="run-receipt.json"))
    (destination / "artifacts/one.md").write_bytes(b"corrupt\n")
    result = verify_package(destination)
    assert result.findings[0].stage == "lineage"
    assert result.last_completed_stage == "item-semantics"


def test_verified_claims_are_curated_bounded_and_not_raw_manifest(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = PackageBuilder(
        package_id="x" * 201,
        request=request(),
        run_id="run-1",
        created_at="2026-07-10T00:00:00Z",
        adapter=AdapterIdentity("fixture", "1.0.0"),
        boundary={"live": "fixture", "deterministic": "assembly"},
        extensions={"org.example.provider": {"secretish": "not-a-claim"}},
    )
    value.add_item(PackageItem("one", "document", ItemOutcome.COMPLETED))
    assert value.seal(destination).ok
    rewrite_manifest(destination, lambda manifest: manifest.update(arbitrary="not-a-claim"))
    result = verify_package(destination)
    assert result.ok and result.schema_version == "2.2.0"
    assert result.verified_claims is not None
    assert result.verified_claims.package_id is None
    assert not hasattr(result.verified_claims, "extensions")
    assert not hasattr(result.verified_claims, "arbitrary")
    assert not hasattr(result, "manifest")
    assert not hasattr(result, "manifest_claims")


def test_consumer_profile_returns_bounded_item_artifact_and_package_claims(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "package"
    value = PackageBuilder(
        package_id="pkg-profile",
        request=request(),
        run_id="run-profile",
        created_at="2026-07-10T00:00:00Z",
        adapter=AdapterIdentity("fixture", "1.0.0", "revision-1"),
        boundary={"live": "fixture", "deterministic": "assembly"},
        extensions={"org.example.provider": {"secretish": "excluded"}},
    )
    value.add_item(
        PackageItem(
            "one",
            "document",
            ItemOutcome.COMPLETED,
            {
                "requested_locator": "https://example.test/requested",
                "resolved_locator": "https://example.test/resolved",
                "canonical_locator": "https://example.test/canonical",
                "language": "en",
                "provenance": {"provider": "fixture", "provider_resource_id": "one"},
                "artifacts": ["artifacts/one/normalized.md"],
                "normalization": {
                    "name": "fixture-normalizer",
                    "version": "1.0.0",
                    "transforms": ["one-trailing-newline"],
                },
                "extensions": {"org.example.provider": {"opaque": "excluded"}},
            },
        )
    )
    value.add_artifact(
        Artifact(
            "artifacts/one/normalized.md",
            b"candidate\n",
            "normalized-content",
            "text/markdown",
        )
    )
    assert value.seal(destination).ok
    profile = ConsumerProfile(identifier="vault-fixture-v1")
    result = verify_package(destination, profile=profile)
    assert result.ok and result.consumer_profile == "vault-fixture-v1"
    claims = result.verified_claims
    assert claims is not None and claims.totals is not None
    assert claims.totals.item_records == 1
    assert claims.totals.aggregate_bytes == sum(
        path.stat().st_size for path in destination.rglob("*") if path.is_file()
    )
    assert claims.item_dispositions[0].canonical_locator == "https://example.test/canonical"
    assert claims.item_dispositions[0].artifact_references == (
        "artifacts/one/normalized.md",
    )
    assert claims.item_dispositions[0].associated_artifacts[0].role == "normalized-content"
    assert claims.item_dispositions[0].finding_references == ()
    artifact = next(
        item for item in claims.artifact_inventory if item.path.endswith("normalized.md")
    )
    assert artifact.role == "normalized-content" and len(artifact.sha256) == 64
    serialized = json.dumps(asdict(result), default=str, sort_keys=True)
    assert "secretish" not in serialized and '"opaque"' not in serialized
    assert "candidate\\n" not in serialized


def test_consumer_profile_resource_limits_fail_closed(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    result = verify_package(
        destination,
        profile=ConsumerProfile(identifier="entry-limit", max_package_entries=1),
    )
    assert result.state == "rejected"
    assert result.consumer_profile == "entry-limit"
    assert {finding.code for finding in result.findings} >= {"consumer-entry-limit"}

    result = verify_package(
        destination,
        profile=ConsumerProfile(identifier="aggregate-limit", max_aggregate_bytes=1),
    )
    assert result.state == "rejected"
    assert result.consumer_profile == "aggregate-limit"
    assert {finding.code for finding in result.findings} >= {
        "consumer-aggregate-size-limit"
    }


def test_consumer_profile_rejects_legacy_argument_mixing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        verify_package(
            tmp_path,
            profile=ConsumerProfile(),
            max_manifest_bytes=1024,
        )


def test_verifier_rejects_unbounded_inventory_metadata_and_unknown_item_refs(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "metadata"
    assert builder().seal(destination).ok
    rewrite_manifest(
        destination,
        lambda manifest: manifest["artifacts"][0].update(role="x" * 201),
    )
    result = verify_package(destination)
    assert result.state == "rejected"
    assert result.findings[0].code == "invalid-inventory-metadata"

    destination = tmp_path / "references"
    assert builder().seal(destination).ok
    item_path = destination / "items/one.json"
    item = json.loads(item_path.read_bytes())
    item["artifacts"] = ["artifacts/missing.md"]
    item_bytes = (
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    item_path.write_bytes(item_bytes)

    def update_item_digest(manifest: dict[str, Any]) -> None:
        entry = next(value for value in manifest["artifacts"] if value["path"] == "items/one.json")
        entry["bytes"] = len(item_bytes)
        entry["sha256"] = hashlib.sha256(item_bytes).hexdigest()

    rewrite_manifest(destination, update_item_digest)
    result = verify_package(destination)
    assert result.state == "rejected"
    assert result.findings[0].code == "invalid-item-artifact-reference"


def test_rejected_result_only_exposes_claims_from_completed_stages(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    rewrite_manifest(destination, lambda manifest: manifest["counts"].update(completed=2))
    result = verify_package(destination)
    assert result.verified_claims is not None
    assert result.verified_claims.package_id == "pkg-1"
    assert result.verified_claims.status is None
    assert result.verified_claims.counts is None


def test_item_read_failure_is_structured_indeterminate_io(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    item_path = destination / "items/one.json"

    def read_bytes(path: Path) -> bytes:
        if path == item_path:
            raise OSError("simulated disappearing item")
        return ORIGINAL_READ_BYTES(path)

    with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-item-read-failure"
    assert result.findings[0].stage == "terminal-accounting"
    assert result.findings[0].reference == "items/one.json"
    assert result.last_completed_stage == "inventory-coverage"


def test_run_receipt_read_failure_is_structured_indeterminate_io(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = builder()
    value.add_artifact(
        Artifact("run-receipt.json", b'{"run_id":"run-1"}\n', "run-receipt", "application/json")
    )
    assert value.seal(destination).ok
    rewrite_manifest(destination, lambda manifest: manifest.update(run_receipt="run-receipt.json"))
    receipt_path = destination / "run-receipt.json"

    def read_bytes(path: Path) -> bytes:
        if path == receipt_path:
            raise OSError("simulated disappearing receipt")
        return ORIGINAL_READ_BYTES(path)

    with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-run-receipt-read-failure"
    assert result.findings[0].reference == "run-receipt.json"
    assert result.last_completed_stage == "item-semantics"


def test_changed_item_is_freshly_read_for_final_integrity(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    item_path = destination / "items/one.json"
    calls = 0

    def read_bytes(path: Path) -> bytes:
        nonlocal calls
        if path == item_path:
            calls += 1
            if calls == 2:
                return ORIGINAL_READ_BYTES(path) + b" "
        return ORIGINAL_READ_BYTES(path)

    with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
        result = verify_package(destination)
    assert calls == 2
    assert result.state == "rejected"
    assert result.findings[0].stage == "artifact-integrity"
    assert result.findings[0].code == "artifact-size-mismatch"


def test_changed_receipt_is_freshly_read_for_final_integrity(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = builder()
    value.add_artifact(
        Artifact("run-receipt.json", b'{"run_id":"run-1"}\n', "run-receipt", "application/json")
    )
    assert value.seal(destination).ok
    rewrite_manifest(destination, lambda manifest: manifest.update(run_receipt="run-receipt.json"))
    receipt_path = destination / "run-receipt.json"
    calls = 0

    def read_bytes(path: Path) -> bytes:
        nonlocal calls
        if path == receipt_path:
            calls += 1
            if calls == 2:
                return ORIGINAL_READ_BYTES(path) + b" "
        return ORIGINAL_READ_BYTES(path)

    with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
        result = verify_package(destination)
    assert calls == 2
    assert result.state == "rejected"
    assert result.findings[0].stage == "artifact-integrity"
    assert result.findings[0].code == "artifact-size-mismatch"


def test_file_disappearing_before_final_integrity_is_indeterminate(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = builder()
    value.add_artifact(
        Artifact("artifacts/one.md", b"candidate\n", "normalized-content", "text/markdown")
    )
    assert value.seal(destination).ok
    candidate_path = destination / "artifacts/one.md"

    def read_bytes(path: Path) -> bytes:
        if path == candidate_path:
            raise OSError("simulated disappearing artifact")
        return ORIGINAL_READ_BYTES(path)

    with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-artifact-read-failure"
    assert result.findings[0].stage == "artifact-integrity"
    assert result.last_completed_stage == "lineage"
    assert result.verified_claims is not None
    assert result.verified_claims.status == "completed"
