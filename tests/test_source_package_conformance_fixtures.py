from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from knowledge_adapters.source_package import verify_package
from tests.source_package_fixtures import materialize_vector

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "source_package_conformance"
MATRIX = json.loads((FIXTURE_ROOT / "vectors.json").read_text(encoding="utf-8"))
VECTORS = MATRIX["vectors"]


def test_matrix_has_unique_cases_and_all_requested_boundaries() -> None:
    ids = [vector["id"] for vector in VECTORS]
    assert len(ids) == len(set(ids)) == 29
    assert {vector["expected"] for vector in VECTORS} == {"accept", "reject"}
    assert sum(vector["expected"] == "accept" for vector in VECTORS) == 3


@pytest.mark.parametrize("vector", VECTORS, ids=lambda vector: str(vector["id"]))
def test_vectors_materialize_deterministically(tmp_path: Path, vector: dict[str, object]) -> None:
    first = materialize_vector(tmp_path / "first", str(vector["mutation"]))
    second = materialize_vector(tmp_path / "second", str(vector["mutation"]))

    first_files = {
        path.relative_to(first): path.read_bytes() for path in first.rglob("*") if path.is_file()
    }
    second_files = {
        path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()
    }
    assert first_files == second_files


@pytest.mark.parametrize(
    "mutation",
    ["minimal_completed", "completed_with_errors", "sealed_receipt"],
)
def test_accepted_vectors_have_exact_manifest_sidecar(tmp_path: Path, mutation: str) -> None:
    package = materialize_vector(tmp_path, mutation)
    manifest_bytes = (package / "package.json").read_bytes()
    assert (package / "package.sha256").read_bytes() == (
        hashlib.sha256(manifest_bytes).hexdigest() + "\n"
    ).encode()


def test_limit_vectors_disclose_non_normative_consumer_limits() -> None:
    limited = [vector for vector in VECTORS if "consumer_limit" in vector]
    assert {vector["id"] for vector in limited} == {"oversized-manifest", "excessive-nesting"}
    assert all("consumer_limit" in vector for vector in limited)


@pytest.mark.parametrize("vector", VECTORS, ids=lambda vector: str(vector["id"]))
def test_public_verifier_matches_conformance_vector(
    tmp_path: Path, vector: dict[str, object]
) -> None:
    package = materialize_vector(tmp_path, str(vector["mutation"]))
    limits = vector.get("consumer_limit", {})
    assert isinstance(limits, dict)
    manifest_limit = int(limits.get("manifest_bytes", 4 * 1024 * 1024))
    depth_limit = int(limits["json_depth"]) if "json_depth" in limits else None
    result = verify_package(
        package,
        max_manifest_bytes=manifest_limit,
        max_json_depth=depth_limit,
    )
    expected_state = "verified" if vector["expected"] == "accept" else "rejected"
    assert result.state == expected_state
    if vector["expected"] == "accept":
        assert result.last_completed_stage == vector["stage"]
    else:
        assert result.findings[0].stage == vector["stage"]
    if "code" in vector:
        assert vector["code"] in {finding.code for finding in result.findings}


def test_public_result_exposes_only_curated_claims(tmp_path: Path) -> None:
    package = materialize_vector(tmp_path, "minimal_completed")
    manifest_path = package / "package.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["extensions"] = {"org.example.provider": {"private": "not-a-claim"}}
    manifest["arbitrary"] = "not-a-claim"
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    (package / "package.sha256").write_bytes(
        (hashlib.sha256(manifest_bytes).hexdigest() + "\n").encode()
    )

    result = verify_package(package)
    assert result.ok and result.schema_version == "2.0.0"
    assert result.verified_claims is not None
    assert result.verified_claims.package_id == "package-001"
    assert not hasattr(result.verified_claims, "extensions")
    assert not hasattr(result.verified_claims, "arbitrary")
    assert not hasattr(result, "manifest")
    assert not hasattr(result, "manifest_claims")


def test_rejected_result_claims_follow_completed_stage(tmp_path: Path) -> None:
    package = materialize_vector(tmp_path, "counts_inconsistent")
    result = verify_package(package)
    assert result.findings[0].stage == "terminal-accounting"
    assert result.verified_claims is not None
    assert result.verified_claims.package_id == "package-001"
    assert result.verified_claims.status is None
    assert result.verified_claims.counts is None
