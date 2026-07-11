import json
from pathlib import Path
from unittest.mock import patch

from knowledge_adapters.source_package import (
    AcquisitionRequest,
    AdapterIdentity,
    Artifact,
    ItemOutcome,
    PackageBuilder,
    PackageItem,
    verify_package,
)


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
    assert result.manifest_claims is None


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
    import hashlib

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
