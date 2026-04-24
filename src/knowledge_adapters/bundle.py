"""Bundle existing adapter artifacts into one prompt-ready markdown file."""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from knowledge_adapters.confluence.manifest import manifest_path

BundleOrder = Literal["canonical_id", "manifest", "input"]
HeaderMode = Literal["minimal", "full"]

DEFAULT_BUNDLE_ORDER: BundleOrder = "canonical_id"
BUNDLE_ORDER_CHOICES: tuple[BundleOrder, ...] = ("canonical_id", "manifest", "input")
BUNDLE_ORDER_LABELS: dict[BundleOrder, str] = {
    "canonical_id": "lexical canonical_id order",
    "manifest": "manifest entry order",
    "input": "input order with manifest grouping",
}
ORDERING_RULE = BUNDLE_ORDER_LABELS[DEFAULT_BUNDLE_ORDER]
DEFAULT_HEADER_MODE: HeaderMode = "full"
HEADER_MODE_CHOICES: tuple[HeaderMode, ...] = ("minimal", "full")
HEADER_MODE_LABELS: dict[HeaderMode, str] = {
    "minimal": "title plus source URL",
    "full": "title, source URL, canonical_id, and optional manifest metadata",
}


@dataclass(frozen=True)
class BundleArtifact:
    """One manifest-backed artifact selected for bundle output."""

    canonical_id: str
    source_url: str
    title: str | None
    output_path: str
    fetched_at: str | None
    path: str | None
    ref: str | None
    content_hash: str | None
    artifact_path: Path


@dataclass(frozen=True)
class BundlePlan:
    """Resolved manifest inputs plus the unique artifacts chosen for output."""

    manifests: tuple[Path, ...]
    artifacts: tuple[BundleArtifact, ...]
    duplicate_canonical_ids: tuple[str, ...]
    filtered_out_count: int = 0
    unchanged_count: int = 0
    baseline_manifest: Path | None = None


@dataclass(frozen=True)
class _BundleArtifactPosition:
    """Stable discovery metadata used to order selected artifacts."""

    input_index: int
    manifest_index: int
    manifest_entry_index: int


@dataclass(frozen=True)
class _BaselineManifestEntry:
    """Prior manifest entry used for changed-only bundle selection."""

    canonical_id: str
    content_hash: str | None
    artifact_path: Path


def describe_bundle_order(order: BundleOrder) -> str:
    """Return the human-readable description for one bundle ordering mode."""
    return BUNDLE_ORDER_LABELS[order]


def describe_header_mode(mode: HeaderMode) -> str:
    """Return the human-readable description for one bundle header mode."""
    return HEADER_MODE_LABELS[mode]


def load_bundle_plan(
    inputs: Sequence[str | Path],
    *,
    order: BundleOrder = DEFAULT_BUNDLE_ORDER,
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    changed_only: bool = False,
    baseline_manifest: str | Path | None = None,
) -> BundlePlan:
    """Load artifacts from output directories or manifest files."""
    if order not in BUNDLE_ORDER_CHOICES:
        raise ValueError(
            f"Unsupported bundle order {order!r}. "
            f"Choose one of: {', '.join(BUNDLE_ORDER_CHOICES)}."
        )
    if changed_only and baseline_manifest is None:
        raise ValueError("Bundle --changed-only requires --baseline-manifest.")
    if baseline_manifest is not None and not changed_only:
        raise ValueError("Bundle --baseline-manifest requires --changed-only.")

    manifests: list[Path] = []
    artifacts_by_id: dict[str, BundleArtifact] = {}
    artifact_positions: dict[str, _BundleArtifactPosition] = {}
    duplicate_canonical_ids: list[str] = []

    for input_index, raw_input in enumerate(inputs):
        manifest = _resolve_manifest_input(raw_input)
        manifests.append(manifest)
        manifest_index = len(manifests) - 1
        for manifest_entry_index, artifact in enumerate(_load_bundle_artifacts(manifest)):
            if artifact.canonical_id in artifacts_by_id:
                duplicate_canonical_ids.append(artifact.canonical_id)
                continue
            artifacts_by_id[artifact.canonical_id] = artifact
            artifact_positions[artifact.canonical_id] = _BundleArtifactPosition(
                input_index=input_index,
                manifest_index=manifest_index,
                manifest_entry_index=manifest_entry_index,
            )

    unchanged_count = 0
    baseline_manifest_path = None
    if changed_only:
        assert baseline_manifest is not None
        baseline_manifest_path = _resolve_manifest_input(baseline_manifest)
        baseline_entries = _load_baseline_manifest_entries(baseline_manifest_path)
        artifacts_by_id, unchanged_count = _select_changed_bundle_artifacts(
            artifacts_by_id,
            baseline_entries,
        )

    ordered_artifacts = _order_bundle_artifacts(
        artifacts_by_id,
        artifact_positions,
        order=order,
    )
    selected_artifacts, filtered_out_count = _filter_bundle_artifacts(
        ordered_artifacts,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )

    return BundlePlan(
        manifests=tuple(manifests),
        artifacts=selected_artifacts,
        duplicate_canonical_ids=tuple(duplicate_canonical_ids),
        filtered_out_count=filtered_out_count,
        unchanged_count=unchanged_count,
        baseline_manifest=baseline_manifest_path,
    )


def render_bundle_markdown(
    artifacts: Sequence[BundleArtifact],
    *,
    header_mode: HeaderMode = DEFAULT_HEADER_MODE,
) -> str:
    """Render bundle output with stable separators and metadata lines."""
    if header_mode not in HEADER_MODE_CHOICES:
        raise ValueError(
            f"Unsupported bundle header mode {header_mode!r}. "
            f"Choose one of: {', '.join(HEADER_MODE_CHOICES)}."
        )

    sections: list[str] = []
    for artifact in artifacts:
        content = _read_artifact_text(artifact)
        sections.append(
            "\n".join(
                (
                    *_render_bundle_header_lines(artifact, header_mode=header_mode),
                    "",
                    content.rstrip("\n"),
                )
            ).rstrip()
        )

    if not sections:
        return ""

    return "\n\n---\n\n".join(sections) + "\n"


def write_bundle(output_path: str | Path, markdown: str) -> Path:
    """Write bundle markdown, creating parent directories when needed."""
    resolved_output_path = Path(output_path).expanduser().resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(markdown, encoding="utf-8")
    return resolved_output_path


def _resolve_manifest_input(raw_input: str | Path) -> Path:
    path = Path(raw_input).expanduser()
    resolved_path = path.resolve()
    if not resolved_path.exists():
        raise ValueError(
            f"Bundle input not found: {resolved_path}. "
            "Provide an existing output directory or manifest file."
        )

    if resolved_path.is_dir():
        resolved_manifest_path = manifest_path(str(resolved_path)).resolve()
        if not resolved_manifest_path.is_file():
            raise ValueError(
                f"Bundle input directory {resolved_path} does not contain manifest.json. "
                "Provide an existing adapter output directory or manifest file."
            )
        return resolved_manifest_path

    if not resolved_path.is_file():
        raise ValueError(
            f"Bundle input is not a file or directory: {resolved_path}. "
            "Provide an existing output directory or manifest file."
        )

    return resolved_path


def _load_bundle_artifacts(manifest: Path) -> tuple[BundleArtifact, ...]:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read bundle manifest {manifest}.") from exc

    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        raise ValueError(
            f"Bundle manifest {manifest} is invalid: expected a files list."
        )

    artifacts: list[BundleArtifact] = []
    manifest_ids: set[str] = set()
    manifest_output_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError(
                f"Bundle manifest {manifest} is invalid: each files entry must be an object."
            )

        canonical_id = entry.get("canonical_id")
        source_url = entry.get("source_url")
        output_path = entry.get("output_path")
        title = entry.get("title")
        fetched_at = _optional_manifest_string(entry, "fetched_at", manifest=manifest)
        path = _optional_manifest_string(entry, "path", manifest=manifest)
        ref = _optional_manifest_string(entry, "ref", manifest=manifest)
        content_hash = _optional_manifest_string(entry, "content_hash", manifest=manifest)
        if not isinstance(canonical_id, str) or not isinstance(source_url, str):
            raise ValueError(
                f"Bundle manifest {manifest} is invalid: files entries must include "
                "string canonical_id and source_url values."
            )
        if not isinstance(output_path, str):
            raise ValueError(
                f"Bundle manifest {manifest} is invalid: files entries must include "
                "a string output_path value."
            )
        if title is not None and not isinstance(title, str):
            raise ValueError(
                f"Bundle manifest {manifest} is invalid: title values must be strings."
            )
        if canonical_id in manifest_ids:
            raise ValueError(
                f"Bundle manifest {manifest} is invalid: duplicate canonical_id "
                f"{canonical_id!r}."
            )
        if output_path in manifest_output_paths:
            raise ValueError(
                f"Bundle manifest {manifest} is invalid: duplicate output_path {output_path!r}."
            )

        manifest_ids.add(canonical_id)
        manifest_output_paths.add(output_path)
        artifacts.append(
            BundleArtifact(
                canonical_id=canonical_id,
                source_url=source_url,
                title=title,
                output_path=output_path,
                fetched_at=fetched_at,
                path=path,
                ref=ref,
                content_hash=content_hash,
                artifact_path=(manifest.parent / output_path).resolve(),
            )
        )

    return tuple(artifacts)


def _load_baseline_manifest_entries(manifest: Path) -> dict[str, _BaselineManifestEntry]:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read baseline manifest {manifest}.") from exc

    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        raise ValueError(
            f"Baseline manifest {manifest} is invalid: expected a files list."
        )

    entries_by_id: dict[str, _BaselineManifestEntry] = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError(
                f"Baseline manifest {manifest} is invalid: each files entry must be an object."
            )

        canonical_id = entry.get("canonical_id")
        output_path = entry.get("output_path")
        content_hash = _optional_manifest_string(entry, "content_hash", manifest=manifest)
        if not isinstance(canonical_id, str) or not isinstance(output_path, str):
            raise ValueError(
                f"Baseline manifest {manifest} is invalid: files entries must include "
                "string canonical_id and output_path values."
            )
        if canonical_id in entries_by_id:
            raise ValueError(
                f"Baseline manifest {manifest} is invalid: duplicate canonical_id "
                f"{canonical_id!r}."
            )

        entries_by_id[canonical_id] = _BaselineManifestEntry(
            canonical_id=canonical_id,
            content_hash=content_hash,
            artifact_path=(manifest.parent / output_path).resolve(),
        )

    return entries_by_id


def _select_changed_bundle_artifacts(
    artifacts_by_id: dict[str, BundleArtifact],
    baseline_entries: dict[str, _BaselineManifestEntry],
) -> tuple[dict[str, BundleArtifact], int]:
    selected_artifacts: dict[str, BundleArtifact] = {}
    unchanged_count = 0
    for canonical_id, artifact in artifacts_by_id.items():
        baseline_entry = baseline_entries.get(canonical_id)
        if baseline_entry is None or _artifact_changed_since_baseline(
            artifact,
            baseline_entry,
        ):
            selected_artifacts[canonical_id] = artifact
        else:
            unchanged_count += 1

    return selected_artifacts, unchanged_count


def _artifact_changed_since_baseline(
    artifact: BundleArtifact,
    baseline_entry: _BaselineManifestEntry,
) -> bool:
    if not baseline_entry.artifact_path.is_file():
        return True

    current_hash = artifact.content_hash or _hash_file(artifact.artifact_path)
    baseline_hash = baseline_entry.content_hash
    if baseline_hash is None:
        try:
            baseline_hash = _hash_file(baseline_entry.artifact_path)
        except ValueError:
            return True

    return current_hash != baseline_hash


def _hash_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"Could not read artifact while computing content hash: {path}.") from exc


def _read_artifact_text(artifact: BundleArtifact) -> str:
    try:
        return artifact.artifact_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"Could not read artifact for canonical_id {artifact.canonical_id!r}: "
            f"{artifact.artifact_path}."
        ) from exc


def _render_bundle_header_lines(
    artifact: BundleArtifact,
    *,
    header_mode: HeaderMode,
) -> tuple[str, ...]:
    title = artifact.title or artifact.canonical_id
    lines = [
        f"## {title}",
        f"source_url: {artifact.source_url}",
    ]
    if header_mode == "minimal":
        return tuple(lines)
    if header_mode == "full":
        lines.append(f"canonical_id: {artifact.canonical_id}")
        for label, value in (
            ("fetched_at", artifact.fetched_at),
            ("path", artifact.path),
            ("ref", artifact.ref),
        ):
            if value:
                lines.append(f"{label}: {value}")
        return tuple(lines)

    raise ValueError(
        f"Unsupported bundle header mode {header_mode!r}. "
        f"Choose one of: {', '.join(HEADER_MODE_CHOICES)}."
    )


def _order_bundle_artifacts(
    artifacts_by_id: dict[str, BundleArtifact],
    artifact_positions: dict[str, _BundleArtifactPosition],
    *,
    order: BundleOrder,
) -> tuple[BundleArtifact, ...]:
    artifacts = tuple(artifacts_by_id.values())
    if order == "canonical_id":
        return tuple(sorted(artifacts, key=lambda artifact: artifact.canonical_id))
    if order == "manifest":
        return tuple(
            sorted(
                artifacts,
                key=lambda artifact: (
                    artifact_positions[artifact.canonical_id].manifest_index,
                    artifact_positions[artifact.canonical_id].manifest_entry_index,
                    artifact.canonical_id,
                ),
            )
        )
    if order == "input":
        return tuple(
            sorted(
                artifacts,
                key=lambda artifact: (
                    artifact_positions[artifact.canonical_id].input_index,
                    artifact_positions[artifact.canonical_id].manifest_entry_index,
                    artifact.canonical_id,
                ),
            )
        )
    raise ValueError(
        f"Unsupported bundle order {order!r}. "
        f"Choose one of: {', '.join(BUNDLE_ORDER_CHOICES)}."
    )


def _filter_bundle_artifacts(
    artifacts: Sequence[BundleArtifact],
    *,
    include_patterns: Sequence[str],
    exclude_patterns: Sequence[str],
) -> tuple[tuple[BundleArtifact, ...], int]:
    selected_artifacts: list[BundleArtifact] = []
    filtered_out_count = 0
    for artifact in artifacts:
        if include_patterns and not _artifact_matches_patterns(artifact, include_patterns):
            filtered_out_count += 1
            continue
        if exclude_patterns and _artifact_matches_patterns(artifact, exclude_patterns):
            filtered_out_count += 1
            continue
        selected_artifacts.append(artifact)

    return tuple(selected_artifacts), filtered_out_count


def _artifact_matches_patterns(
    artifact: BundleArtifact,
    patterns: Sequence[str],
) -> bool:
    artifact_values = (
        artifact.canonical_id,
        artifact.title,
        artifact.output_path,
        artifact.source_url,
    )
    return any(
        value is not None and fnmatch.fnmatchcase(value, pattern)
        for pattern in patterns
        for value in artifact_values
    )


def _optional_manifest_string(
    entry: dict[str, object],
    field_name: str,
    *,
    manifest: Path,
) -> str | None:
    value = entry.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"Bundle manifest {manifest} is invalid: {field_name} values must be strings."
        )
    return value or None
