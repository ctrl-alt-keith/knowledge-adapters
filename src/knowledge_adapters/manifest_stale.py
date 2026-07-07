"""Shared helpers for manifest-backed artifact cleanup."""

from __future__ import annotations

import json
import stat
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreviousManifestEntry:
    """Normalized prior-manifest entry used for stale-artifact comparisons."""

    canonical_id: str
    output_path: str
    page_version: str | None
    last_modified: str | None
    content_hash: str | None


@dataclass(frozen=True)
class StaleArtifact:
    """Previously written artifact no longer part of the current run output."""

    canonical_id: str
    output_path: str


@dataclass(frozen=True)
class PrunedArtifact:
    """Stale manifest-owned artifact removed from disk."""

    canonical_id: str
    output_path: str
    path: Path


@dataclass(frozen=True)
class OrphanedArtifact:
    """Generated markdown artifact not referenced by the current run output."""

    output_path: str


@dataclass(frozen=True)
class PrunedOrphanedArtifact:
    """Orphaned generated markdown artifact removed from disk."""

    output_path: str
    path: Path


def _normalize_metadata_value(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def _load_previous_manifest_indexes(
    output_dir: str,
) -> tuple[dict[str, PreviousManifestEntry], dict[str, str]] | None:
    """Load and validate the previous manifest for incremental comparisons."""
    path = Path(output_dir) / "manifest.json"
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read prior manifest {path}. Fix or remove the manifest and try again."
        ) from exc

    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError(
            f"Prior manifest {path} is invalid: expected a files list. "
            "Fix or remove the manifest and try again."
        )

    entries_by_id: dict[str, PreviousManifestEntry] = {}
    entries_by_output_path: dict[str, str] = {}

    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"Prior manifest {path} is invalid: each files entry must be an object. "
                "Fix or remove the manifest and try again."
            )

        canonical_id = entry.get("canonical_id")
        output_path = entry.get("output_path")
        if not isinstance(canonical_id, str) or not isinstance(output_path, str):
            raise RuntimeError(
                f"Prior manifest {path} is invalid: files entries must include string "
                "canonical_id and output_path values. Fix or remove the manifest and try again."
            )

        if canonical_id in entries_by_id:
            raise RuntimeError(
                f"Prior manifest {path} is invalid: duplicate canonical_id {canonical_id!r}. "
                "Fix or remove the manifest and try again."
            )
        if output_path in entries_by_output_path:
            raise RuntimeError(
                f"Prior manifest {path} is invalid: duplicate output_path {output_path!r}. "
                "Fix or remove the manifest and try again."
            )

        entries_by_id[canonical_id] = PreviousManifestEntry(
            canonical_id=canonical_id,
            output_path=output_path,
            page_version=_normalize_metadata_value(entry.get("page_version")),
            last_modified=_normalize_metadata_value(entry.get("last_modified")),
            content_hash=_normalize_metadata_value(entry.get("content_hash")),
        )
        entries_by_output_path[output_path] = canonical_id

    return entries_by_id, entries_by_output_path


def load_previous_manifest_index(output_dir: str) -> dict[str, PreviousManifestEntry] | None:
    """Load and validate the previous manifest keyed by canonical_id."""
    indexes = _load_previous_manifest_indexes(output_dir)
    if indexes is None:
        return None

    return indexes[0]


def load_previous_manifest_output_index(output_dir: str) -> dict[str, str] | None:
    """Load and validate the previous manifest keyed by output_path."""
    indexes = _load_previous_manifest_indexes(output_dir)
    if indexes is None:
        return None

    return indexes[1]


def find_stale_artifacts(
    output_dir: str,
    previous_manifest_index: dict[str, PreviousManifestEntry] | None,
    *,
    current_output_paths: Collection[str],
) -> list[StaleArtifact]:
    """Return prior manifest artifacts no longer present in the current run output."""
    if previous_manifest_index is None:
        return []

    current_paths = frozenset(current_output_paths)
    output_dir_path = Path(output_dir)
    stale_artifacts: list[StaleArtifact] = []

    for canonical_id, prior_entry in sorted(
        previous_manifest_index.items(),
        key=lambda item: (item[1].output_path, item[0]),
    ):
        if prior_entry.output_path in current_paths:
            continue

        artifact_path = output_dir_path / prior_entry.output_path
        if not artifact_path.exists():
            continue

        stale_artifacts.append(
            StaleArtifact(
                canonical_id=canonical_id,
                output_path=prior_entry.output_path,
            )
        )

    return stale_artifacts


def plan_stale_artifact_prune(
    output_dir: str | Path,
    stale_artifacts: Collection[StaleArtifact],
) -> list[PrunedArtifact]:
    """Validate stale-artifact prune candidates without deleting anything."""
    output_dir_path = Path(output_dir).expanduser().resolve()
    pruned_artifacts: list[PrunedArtifact] = []
    validation_errors: list[str] = []

    for artifact in sorted(stale_artifacts, key=lambda item: (item.output_path, item.canonical_id)):
        artifact_path = output_dir_path / artifact.output_path
        try:
            resolved_artifact_path = artifact_path.resolve(strict=True)
        except OSError as exc:
            validation_errors.append(
                f"{artifact.output_path!r} ({artifact.canonical_id}) could not be resolved: {exc}"
            )
            continue

        try:
            resolved_artifact_path.relative_to(output_dir_path)
        except ValueError:
            validation_errors.append(
                f"{artifact.output_path!r} ({artifact.canonical_id}) resolves outside "
                f"output_dir {output_dir_path}: {resolved_artifact_path}"
            )
            continue

        try:
            artifact_stat = artifact_path.stat(follow_symlinks=False)
        except OSError as exc:
            validation_errors.append(
                f"{artifact.output_path!r} ({artifact.canonical_id}) could not be inspected: {exc}"
            )
            continue

        if not stat.S_ISREG(artifact_stat.st_mode):
            validation_errors.append(
                f"{artifact.output_path!r} ({artifact.canonical_id}) is not a regular file"
            )
            continue

        pruned_artifacts.append(
            PrunedArtifact(
                canonical_id=artifact.canonical_id,
                output_path=artifact.output_path,
                path=resolved_artifact_path,
            )
        )

    if validation_errors:
        details = "\n  ".join(validation_errors)
        raise RuntimeError(f"Could not safely prune stale artifacts:\n  {details}")

    return pruned_artifacts


def prune_stale_artifacts(
    output_dir: str | Path,
    stale_artifacts: Collection[StaleArtifact],
) -> list[PrunedArtifact]:
    """Delete validated stale manifest-owned regular files under output_dir."""
    pruned_artifacts = plan_stale_artifact_prune(output_dir, stale_artifacts)
    for artifact in pruned_artifacts:
        try:
            artifact.path.unlink()
        except OSError as exc:
            raise RuntimeError(f"Could not prune stale artifact {artifact.path}: {exc}") from exc
    return pruned_artifacts


def find_orphaned_artifacts(
    output_dir: str | Path,
    *,
    current_output_paths: Collection[str],
    output_subdirectories: Collection[str] = ("pages",),
) -> list[OrphanedArtifact]:
    """Return unreferenced generated markdown artifacts under configured output roots."""
    output_dir_path = Path(output_dir).expanduser()
    artifact_subdirectories = _normalize_output_subdirectories(output_subdirectories)

    current_paths = frozenset(_normalize_output_path(path) for path in current_output_paths)
    orphaned_artifacts: list[OrphanedArtifact] = []
    orphaned_output_paths: set[str] = set()

    for output_subdirectory in artifact_subdirectories:
        artifact_root = output_dir_path / output_subdirectory
        if not artifact_root.exists():
            continue

        for artifact_path in artifact_root.rglob("*.md"):
            try:
                relative_output_path = artifact_path.relative_to(output_dir_path).as_posix()
            except ValueError:
                continue
            if _normalize_output_path(relative_output_path) in current_paths:
                continue
            if relative_output_path in orphaned_output_paths:
                continue
            try:
                artifact_stat = artifact_path.lstat()
            except OSError:
                continue
            if stat.S_ISREG(artifact_stat.st_mode):
                orphaned_output_paths.add(relative_output_path)
                orphaned_artifacts.append(OrphanedArtifact(output_path=relative_output_path))

    return sorted(orphaned_artifacts, key=lambda artifact: artifact.output_path)


def plan_orphaned_artifact_prune(
    output_dir: str | Path,
    orphaned_artifacts: Collection[OrphanedArtifact],
    *,
    current_output_paths: Collection[str] = (),
    output_subdirectories: Collection[str] = ("pages",),
) -> list[PrunedOrphanedArtifact]:
    """Validate orphaned-artifact prune candidates without deleting anything."""
    output_dir_path = Path(output_dir).expanduser().resolve()
    artifact_subdirectories = _normalize_output_subdirectories(output_subdirectories)
    artifact_roots = tuple(output_dir_path / subdir for subdir in artifact_subdirectories)
    current_paths = frozenset(_normalize_output_path(path) for path in current_output_paths)
    pruned_artifacts: list[PrunedOrphanedArtifact] = []
    validation_errors: list[str] = []

    for artifact in sorted(orphaned_artifacts, key=lambda item: item.output_path):
        normalized_output_path = _normalize_output_path(artifact.output_path)
        artifact_path = output_dir_path / normalized_output_path

        if normalized_output_path in current_paths:
            validation_errors.append(
                f"{artifact.output_path!r} is referenced by the current run plan"
            )
            continue
        if Path(normalized_output_path).is_absolute():
            validation_errors.append(f"{artifact.output_path!r} is not a relative path")
            continue
        if not _is_under_any_output_subdirectory(
            normalized_output_path,
            artifact_subdirectories,
        ):
            validation_errors.append(
                f"{artifact.output_path!r} is outside configured output subdirectories"
            )
            continue
        if artifact_path.suffix != ".md":
            validation_errors.append(f"{artifact.output_path!r} is not a markdown artifact")
            continue

        try:
            resolved_artifact_path = artifact_path.resolve(strict=True)
        except OSError as exc:
            validation_errors.append(f"{artifact.output_path!r} could not be resolved: {exc}")
            continue

        try:
            resolved_artifact_path.relative_to(output_dir_path)
        except ValueError:
            validation_errors.append(
                f"{artifact.output_path!r} resolves outside output_dir "
                f"{output_dir_path}: {resolved_artifact_path}"
            )
            continue

        if not any(
            _is_relative_to(resolved_artifact_path, artifact_root)
            for artifact_root in artifact_roots
        ):
            validation_errors.append(
                f"{artifact.output_path!r} resolves outside configured output "
                f"subdirectories: {resolved_artifact_path}"
            )
            continue

        try:
            artifact_stat = artifact_path.stat(follow_symlinks=False)
        except OSError as exc:
            validation_errors.append(f"{artifact.output_path!r} could not be inspected: {exc}")
            continue

        if not stat.S_ISREG(artifact_stat.st_mode):
            validation_errors.append(f"{artifact.output_path!r} is not a regular file")
            continue

        pruned_artifacts.append(
            PrunedOrphanedArtifact(
                output_path=normalized_output_path,
                path=resolved_artifact_path,
            )
        )

    if validation_errors:
        details = "\n  ".join(validation_errors)
        raise RuntimeError(f"Could not safely prune orphaned artifacts:\n  {details}")

    return pruned_artifacts


def prune_orphaned_artifacts(
    output_dir: str | Path,
    orphaned_artifacts: Collection[OrphanedArtifact],
    *,
    current_output_paths: Collection[str] = (),
    output_subdirectories: Collection[str] = ("pages",),
) -> list[PrunedOrphanedArtifact]:
    """Delete validated orphaned markdown artifacts under configured output roots."""
    pruned_artifacts = plan_orphaned_artifact_prune(
        output_dir,
        orphaned_artifacts,
        current_output_paths=current_output_paths,
        output_subdirectories=output_subdirectories,
    )
    for artifact in pruned_artifacts:
        try:
            artifact.path.unlink()
        except OSError as exc:
            raise RuntimeError(f"Could not prune orphaned artifact {artifact.path}: {exc}") from exc
    return pruned_artifacts


def _normalize_output_path(output_path: str) -> str:
    return Path(output_path).as_posix().removeprefix("./")


def _normalize_output_subdirectories(output_subdirectories: Collection[str]) -> tuple[str, ...]:
    normalized_subdirectories: list[str] = []
    seen: set[str] = set()

    for output_subdirectory in output_subdirectories:
        normalized = _normalize_output_path(output_subdirectory).removesuffix("/")
        path = Path(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError(
                "orphan artifact output_subdirectories must be relative "
                "subdirectories under output_dir"
            )
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_subdirectories.append(normalized)

    return tuple(normalized_subdirectories)


def _is_under_any_output_subdirectory(
    output_path: str,
    output_subdirectories: Collection[str],
) -> bool:
    output_path_parts = Path(output_path).parts
    return any(
        output_path_parts[: len(Path(output_subdirectory).parts)] == Path(output_subdirectory).parts
        for output_subdirectory in output_subdirectories
    )


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True
