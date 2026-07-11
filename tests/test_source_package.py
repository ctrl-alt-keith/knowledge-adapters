import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from knowledge_adapters.source_package import (
    COLLECTION_PROGRESS_CAPABILITY,
    AcquisitionRequest,
    AdapterIdentity,
    Artifact,
    CollectionProgress,
    CollectionProgressState,
    ConsumerProfile,
    ItemOutcome,
    PackageBuilder,
    PackageItem,
    PackageLineage,
    verify_package,
)
from knowledge_adapters.source_package import core as source_package_core


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


def test_builder_seals_typed_collection_progress_and_resume_lineage(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = PackageBuilder(
        package_id="pkg-resumed",
        request=request(),
        run_id="run-2",
        created_at="2026-07-10T01:00:00Z",
        adapter=AdapterIdentity("fixture", "1.0.0"),
        contract_version="1.1.0",
        boundary={"live": "fixture", "deterministic": "assembly"},
        collection_progress=CollectionProgress(
            CollectionProgressState.CONTINUATION_REMAINING
        ),
        lineage=PackageLineage(
            resumes_run_id="run-1",
            prior_package_ids=("pkg-1",),
            prior_run_ids=("run-1",),
            reconciliation_summary={"reused": 1},
            final_attempt_counts={"one": 2},
        ),
    )
    value.add_item(PackageItem("one", "document", ItemOutcome.UNCHANGED))
    assert value.seal(destination).ok
    manifest = json.loads((destination / "package.json").read_bytes())
    assert manifest["collection_progress"] == {"state": "continuation_remaining"}
    assert manifest["resumes_run_id"] == "run-1"
    assert manifest["required_capabilities"] == [COLLECTION_PROGRESS_CAPABILITY]

    result = verify_package(
        destination,
        profile=ConsumerProfile(
            identifier="progress-profile",
            supported_capabilities=(COLLECTION_PROGRESS_CAPABILITY,),
            max_item_records=1,
        ),
    )
    assert result.ok
    assert result.consumer_profile == "progress-profile"
    assert result.schema_version == "2.3.0"
    assert result.verified_claims is not None
    assert result.verified_claims.schema_version == "1.3.0"
    assert result.verified_claims.collection_progress == CollectionProgress(
        CollectionProgressState.CONTINUATION_REMAINING
    )
    assert result.verified_claims.resumes_run_id == "run-1"
    assert result.verified_claims.totals is not None
    assert result.verified_claims.totals.item_records == 1
    assert len(result.verified_claims.item_dispositions) == 1


def test_collection_progress_requires_consumer_capability(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    value = PackageBuilder(
        package_id="pkg-progress",
        request=request(),
        run_id="run-1",
        created_at="2026-07-10T00:00:00Z",
        adapter=AdapterIdentity("fixture", "1.0.0"),
        contract_version="1.1.0",
        boundary={"live": "fixture", "deterministic": "assembly"},
        collection_progress=CollectionProgress(CollectionProgressState.EXHAUSTED),
    )
    value.add_item(PackageItem("one", "document", ItemOutcome.COMPLETED))
    assert value.seal(destination).ok
    result = verify_package(
        destination,
        profile=ConsumerProfile(identifier="no-progress-profile"),
    )
    assert result.state == "rejected"
    assert result.consumer_profile == "no-progress-profile"
    assert result.findings[0].code == "unknown-required-capability"
    assert result.verified_claims is None


def test_builder_preserves_v1_0_default_and_requires_v1_1_for_progress(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "plain"
    assert builder().seal(destination).ok
    manifest = json.loads((destination / "package.json").read_bytes())
    assert manifest["contract_version"] == "1.0.0"
    try:
        PackageBuilder(
            package_id="pkg-progress",
            request=request(),
            run_id="run-1",
            created_at="2026-07-10T00:00:00Z",
            adapter=AdapterIdentity("fixture", "1.0.0"),
            boundary={"live": "fixture", "deterministic": "assembly"},
            collection_progress=CollectionProgress(CollectionProgressState.EXHAUSTED),
        )
    except ValueError as exc:
        assert "contract_version 1.1.0" in str(exc)
    else:
        raise AssertionError("v1.0 package accepted collection progress")


@pytest.mark.parametrize(
    ("lineage", "message"),
    [
        (
            PackageLineage(
                resumes_run_id="run-0",
                reconciliation_summary={},
                final_attempt_counts={},
            ),
            "resumes_run_id must appear in prior_run_ids",
        ),
        (
            PackageLineage(
                resumes_run_id="run-0",
                prior_run_ids=("run-other",),
                reconciliation_summary={},
                final_attempt_counts={},
            ),
            "resumes_run_id must appear in prior_run_ids",
        ),
        (
            PackageLineage(
                resumes_run_id="run-0",
                prior_run_ids=("run-0",),
                final_attempt_counts={},
            ),
            "requires reconciliation_summary",
        ),
        (
            PackageLineage(
                resumes_run_id="run-0",
                prior_run_ids=("run-0",),
                reconciliation_summary={},
            ),
            "requires final_attempt_counts",
        ),
        (
            PackageLineage(
                resumes_run_id="run-1",
                prior_run_ids=("run-1",),
                reconciliation_summary={},
                final_attempt_counts={},
            ),
            "must not equal the current run_id",
        ),
        (
            PackageLineage(prior_package_ids=("pkg-progress",)),
            "must not contain the current package_id",
        ),
    ],
)
def test_builder_rejects_incomplete_or_self_referential_lineage(
    lineage: PackageLineage,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PackageBuilder(
            package_id="pkg-progress",
            request=request(),
            run_id="run-1",
            created_at="2026-07-10T00:00:00Z",
            adapter=AdapterIdentity("fixture", "1.0.0"),
            boundary={"live": "fixture", "deterministic": "assembly"},
            lineage=lineage,
        )


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
    assert result.ok and result.schema_version == "2.3.0"
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


def test_descriptor_bound_package_read_succeeds_normally(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    data = source_package_core._bounded_package_read(
        destination, "items/one.json", 1024 * 1024
    )
    assert json.loads(data)["item_id"] == "one"


def test_path_read_bytes_monkeypatch_cannot_bypass_production_reader(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    with patch.object(Path, "read_bytes", side_effect=AssertionError("must not be called")):
        result = verify_package(destination)
    assert result.ok


def test_descriptor_reader_fails_closed_without_required_platform_primitives(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    with patch.object(os, "supports_dir_fd", set()):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-read-failure"
    assert result.verified_claims is None


def test_final_same_byte_external_symlink_is_indeterminate_without_leakage(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    outside = tmp_path / "external-secret-location.json"
    outside.write_bytes((destination / "request.json").read_bytes())

    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_final_open" and relative == "request.json":
            target = package / relative
            target.unlink()
            target.symlink_to(outside)

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
        result = verify_package(destination)
    serialized = json.dumps(asdict(result), default=str)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-artifact-read-failure"
    assert result.last_completed_stage == "lineage"
    assert result.verified_claims is not None
    assert "external-secret-location" not in serialized
    assert str(tmp_path) not in serialized


def test_intermediate_symlink_is_indeterminate(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    outside = tmp_path / "external-secret-items"
    outside.mkdir()
    outside_marker = "UNIQUE_EXTERNAL_ITEM_BYTES_MUST_NOT_LEAK"
    (outside / "one.json").write_text(outside_marker, encoding="utf-8")

    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_component_open" and relative == "items/one.json":
            shutil.rmtree(package / "items")
            (package / "items").symlink_to(outside, target_is_directory=True)

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-item-read-failure"
    assert result.last_completed_stage == "inventory-coverage"
    serialized = json.dumps(asdict(result), default=str)
    assert "external-secret-items" not in serialized
    assert outside_marker not in serialized


def test_different_inode_before_open_is_indeterminate(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok

    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_final_open" and relative == "items/one.json":
            target = package / relative
            replacement = target.with_suffix(".replacement")
            replacement.write_bytes(target.read_bytes())
            replacement.replace(target)

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-item-read-failure"


def test_mutation_after_first_descriptor_read_is_indeterminate(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok

    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "after_first_read" and relative == "items/one.json":
            target = package / relative
            target.write_bytes(target.read_bytes() + b" ")

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-item-read-failure"


def test_disappearance_before_descriptor_open_is_indeterminate(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok

    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_final_open" and relative == "items/one.json":
            (package / relative).unlink()

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-item-read-failure"


def test_descriptor_read_attempts_to_close_every_open_fd_without_masking_failure(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    opened: list[int] = []
    closed: list[int] = []
    original_open, original_close = os.open, os.close

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = original_open(*args, **kwargs)  # type: ignore[arg-type]
        opened.append(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)
        raise OSError("simulated close failure")

    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_final_open":
            raise OSError("primary safe-read failure")

    with patch.object(os, "open", side_effect=tracked_open) as open_mock:
        supported_dir_fd = set(os.supports_dir_fd) | {open_mock}
        with (
            patch.object(os, "supports_dir_fd", supported_dir_fd),
            patch.object(os, "close", side_effect=tracked_close),
            patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook),
        ):
            with pytest.raises(OSError, match="primary safe-read failure"):
                source_package_core._bounded_package_read(
                    destination, "items/one.json", 1024 * 1024
                )
    assert opened
    assert sorted(opened) == sorted(closed)


def test_item_read_failure_is_structured_indeterminate_io(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_path_stat" and relative == "items/one.json":
            raise OSError("simulated disappearing item")

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
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
    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_path_stat" and relative == "run-receipt.json":
            raise OSError("simulated disappearing receipt")

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-run-receipt-read-failure"
    assert result.findings[0].reference == "run-receipt.json"
    assert result.last_completed_stage == "item-semantics"


def test_changed_item_is_freshly_read_for_final_integrity(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    calls = 0

    def read_hook(phase: str, package: Path, relative: str) -> None:
        nonlocal calls
        if phase == "before_path_stat" and relative == "items/one.json":
            calls += 1
            if calls == 2:
                (package / "items/one.json").write_bytes(
                    (package / "items/one.json").read_bytes() + b" "
                )

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
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
    calls = 0

    def read_hook(phase: str, package: Path, relative: str) -> None:
        nonlocal calls
        if phase == "before_path_stat" and relative == "run-receipt.json":
            calls += 1
            if calls == 2:
                (package / "run-receipt.json").write_bytes(
                    (package / "run-receipt.json").read_bytes() + b" "
                )

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
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
    def read_hook(phase: str, package: Path, relative: str) -> None:
        if phase == "before_path_stat" and relative == "artifacts/one.md":
            raise OSError("simulated disappearing artifact")

    with patch.object(source_package_core, "_PACKAGE_READ_TEST_HOOK", read_hook):
        result = verify_package(destination)
    assert result.state == "indeterminate_io"
    assert result.findings[0].code == "io-artifact-read-failure"
    assert result.findings[0].stage == "artifact-integrity"
    assert result.last_completed_stage == "lineage"
    assert result.verified_claims is not None
    assert result.verified_claims.status == "completed"
