from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_adapters.manifest_stale import (
    OrphanedArtifact,
    StaleArtifact,
    find_orphaned_artifacts,
    plan_orphaned_artifact_prune,
    plan_stale_artifact_prune,
    prune_orphaned_artifacts,
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


def test_find_orphaned_artifacts_reports_unreferenced_markdown_under_pages(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    kept = output_dir / "pages" / "kept.md"
    orphaned = output_dir / "pages" / "nested" / "orphaned.md"
    non_markdown = output_dir / "pages" / "nested" / "ignored.txt"
    outside_pages = output_dir / "other" / "orphaned.md"
    directory = output_dir / "pages" / "dir.md"
    for path in (kept, orphaned, non_markdown, outside_pages):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    directory.mkdir()

    orphaned_artifacts = find_orphaned_artifacts(
        output_dir,
        current_output_paths=["pages/kept.md"],
    )

    assert [artifact.output_path for artifact in orphaned_artifacts] == ["pages/nested/orphaned.md"]


def test_find_orphaned_artifacts_scans_configured_output_subdirectories(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    kept = output_dir / "issues" / "2.md"
    orphaned_issue = output_dir / "issues" / "7.md"
    orphaned_release = output_dir / "releases" / "9.md"
    ignored_page = output_dir / "pages" / "old.md"
    for path in (kept, orphaned_issue, orphaned_release, ignored_page):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    orphaned_artifacts = find_orphaned_artifacts(
        output_dir,
        current_output_paths=["issues/2.md"],
        output_subdirectories=("issues", "pull_requests", "releases"),
    )

    assert [artifact.output_path for artifact in orphaned_artifacts] == [
        "issues/7.md",
        "releases/9.md",
    ]


def test_find_orphaned_artifacts_does_not_report_markdown_symlinks(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    real_orphaned = output_dir / "pages" / "real.md"
    symlink_orphaned = output_dir / "pages" / "linked.md"
    outside_target = tmp_path / "outside.md"
    real_orphaned.parent.mkdir(parents=True)
    real_orphaned.write_text("real\n", encoding="utf-8")
    outside_target.write_text("outside\n", encoding="utf-8")
    try:
        symlink_orphaned.symlink_to(outside_target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    orphaned_artifacts = find_orphaned_artifacts(
        output_dir,
        current_output_paths=[],
    )

    assert [artifact.output_path for artifact in orphaned_artifacts] == ["pages/real.md"]


def test_find_orphaned_artifacts_does_not_report_uninspectable_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    visible = output_dir / "pages" / "visible.md"
    uninspectable = output_dir / "pages" / "uninspectable.md"
    for path in (visible, uninspectable):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    original_lstat = Path.lstat

    def fake_lstat(self: Path) -> object:
        if self == uninspectable:
            raise OSError("cannot inspect")
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    orphaned_artifacts = find_orphaned_artifacts(
        output_dir,
        current_output_paths=[],
    )

    assert [artifact.output_path for artifact in orphaned_artifacts] == ["pages/visible.md"]


def test_prune_orphaned_artifacts_deletes_only_unreferenced_markdown_under_pages(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    kept = output_dir / "pages" / "kept.md"
    orphaned = output_dir / "pages" / "orphaned.md"
    non_markdown = output_dir / "pages" / "ignored.txt"
    outside_pages = output_dir / "other" / "orphaned.md"
    for path in (kept, orphaned, non_markdown, outside_pages):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    orphaned_artifacts = find_orphaned_artifacts(
        output_dir,
        current_output_paths=["pages/kept.md"],
    )
    pruned = prune_orphaned_artifacts(
        output_dir,
        orphaned_artifacts,
        current_output_paths=["pages/kept.md"],
    )

    assert [artifact.output_path for artifact in pruned] == ["pages/orphaned.md"]
    assert kept.read_text(encoding="utf-8") == "kept.md"
    assert not orphaned.exists()
    assert non_markdown.read_text(encoding="utf-8") == "ignored.txt"
    assert outside_pages.read_text(encoding="utf-8") == "orphaned.md"


def test_prune_orphaned_artifacts_deletes_configured_output_subdirectory_orphans(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    kept = output_dir / "issues" / "2.md"
    orphaned = output_dir / "pull_requests" / "4.md"
    outside_layout = output_dir / "pages" / "old.md"
    for path in (kept, orphaned, outside_layout):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    orphaned_artifacts = find_orphaned_artifacts(
        output_dir,
        current_output_paths=["issues/2.md"],
        output_subdirectories=("issues", "pull_requests", "releases"),
    )
    pruned = prune_orphaned_artifacts(
        output_dir,
        orphaned_artifacts,
        current_output_paths=["issues/2.md"],
        output_subdirectories=("issues", "pull_requests", "releases"),
    )

    assert [artifact.output_path for artifact in pruned] == ["pull_requests/4.md"]
    assert kept.read_text(encoding="utf-8") == "2.md"
    assert not orphaned.exists()
    assert outside_layout.read_text(encoding="utf-8") == "old.md"


def test_plan_orphaned_artifact_prune_does_not_delete_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    orphaned = output_dir / "pages" / "orphaned.md"
    orphaned.parent.mkdir(parents=True)
    orphaned.write_text("orphaned\n", encoding="utf-8")

    planned = plan_orphaned_artifact_prune(
        output_dir,
        (OrphanedArtifact(output_path="pages/orphaned.md"),),
    )

    assert [artifact.output_path for artifact in planned] == ["pages/orphaned.md"]
    assert orphaned.read_text(encoding="utf-8") == "orphaned\n"


def test_prune_orphaned_artifacts_rejects_unsafe_candidates_before_deleting(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    safe_orphaned = output_dir / "pages" / "safe.md"
    outside_target = tmp_path / "outside.md"
    unsafe_link = output_dir / "pages" / "unsafe.md"
    safe_orphaned.parent.mkdir(parents=True)
    safe_orphaned.write_text("safe\n", encoding="utf-8")
    outside_target.write_text("outside\n", encoding="utf-8")
    try:
        unsafe_link.symlink_to(outside_target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(RuntimeError, match="outside output_dir"):
        prune_orphaned_artifacts(
            output_dir,
            (
                OrphanedArtifact(output_path="pages/safe.md"),
                OrphanedArtifact(output_path="pages/unsafe.md"),
            ),
        )

    assert safe_orphaned.read_text(encoding="utf-8") == "safe\n"
    assert outside_target.read_text(encoding="utf-8") == "outside\n"
    assert unsafe_link.is_symlink()


def test_prune_orphaned_artifacts_rejects_referenced_candidates_before_deleting(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    referenced = output_dir / "pages" / "referenced.md"
    other = output_dir / "pages" / "other.md"
    for path in (referenced, other):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    with pytest.raises(RuntimeError, match="referenced by the current run plan"):
        prune_orphaned_artifacts(
            output_dir,
            (
                OrphanedArtifact(output_path="pages/referenced.md"),
                OrphanedArtifact(output_path="pages/other.md"),
            ),
            current_output_paths=["pages/referenced.md"],
        )

    assert referenced.read_text(encoding="utf-8") == "referenced.md"
    assert other.read_text(encoding="utf-8") == "other.md"
