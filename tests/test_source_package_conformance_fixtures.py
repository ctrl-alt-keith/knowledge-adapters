from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.source_package_fixtures import materialize_vector

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "source_package_conformance"
MATRIX = json.loads((FIXTURE_ROOT / "vectors.json").read_text(encoding="utf-8"))
VECTORS = MATRIX["vectors"]


def test_matrix_has_unique_cases_and_all_requested_boundaries() -> None:
    ids = [vector["id"] for vector in VECTORS]
    assert len(ids) == len(set(ids)) == 25
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
    limited = [vector for vector in VECTORS if vector["stage"] == "consumer-limit"]
    assert {vector["id"] for vector in limited} == {"oversized-manifest", "excessive-nesting"}
    assert all("consumer_limit" in vector for vector in limited)
