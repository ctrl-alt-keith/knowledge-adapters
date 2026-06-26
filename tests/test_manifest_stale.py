from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_adapters.manifest_stale import (
    StaleArtifact,
    plan_stale_artifact_prune,
    prune_stale_artifacts,
)


def test_prune_stale_artifacts_deletes_regular_files_in_deterministic_order(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    first = output_dir / "pages" / "a.md"
    second = output_dir / "pages" / "b.md"
    unmanifested = output_dir / "pages" / "keep.md"
    for path in (first, second, unmanifested):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    pruned = prune_stale_artifacts(
        output_dir,
        (
            StaleArtifact(canonical_id="second", output_path="pages/b.md"),
            StaleArtifact(canonical_id="first", output_path="pages/a.md"),
        ),
    )

    assert [(artifact.canonical_id, artifact.output_path) for artifact in pruned] == [
        ("first", "pages/a.md"),
        ("second", "pages/b.md"),
    ]
    assert not first.exists()
    assert not second.exists()
    assert unmanifested.read_text(encoding="utf-8") == "keep.md"


def test_plan_stale_artifact_prune_does_not_delete_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    stale_file = output_dir / "pages" / "stale.md"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("stale\n", encoding="utf-8")

    planned = plan_stale_artifact_prune(
        output_dir,
        (StaleArtifact(canonical_id="stale", output_path="pages/stale.md"),),
    )

    assert [(artifact.canonical_id, artifact.output_path) for artifact in planned] == [
        ("stale", "pages/stale.md")
    ]
    assert stale_file.read_text(encoding="utf-8") == "stale\n"


def test_prune_stale_artifacts_rejects_outside_paths_before_deleting_anything(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    safe_file = output_dir / "pages" / "safe.md"
    outside_file = tmp_path / "outside.md"
    safe_file.parent.mkdir(parents=True)
    safe_file.write_text("safe\n", encoding="utf-8")
    outside_file.write_text("outside\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="outside output_dir"):
        prune_stale_artifacts(
            output_dir,
            (
                StaleArtifact(canonical_id="safe", output_path="pages/safe.md"),
                StaleArtifact(canonical_id="outside", output_path=str(outside_file)),
            ),
        )

    assert safe_file.read_text(encoding="utf-8") == "safe\n"
    assert outside_file.read_text(encoding="utf-8") == "outside\n"


def test_prune_stale_artifacts_rejects_directories_without_deleting_them(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    stale_dir = output_dir / "pages" / "stale-dir"
    stale_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="not a regular file"):
        prune_stale_artifacts(
            output_dir,
            (StaleArtifact(canonical_id="stale-dir", output_path="pages/stale-dir"),),
        )

    assert stale_dir.is_dir()
