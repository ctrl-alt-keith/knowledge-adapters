"""Bounded mutable checkpoint state outside Source Packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from knowledge_adapters.source_package import canonical_json_bytes

from .config import MAX_CAPTION_BYTES, MAX_COLLECTION_ITEMS, VIDEO_ID_RE

CHECKPOINT_SCHEMA_VERSION = "1.2.0"
MAX_CHECKPOINT_BYTES = 1024 * 1024
MAX_CHECKPOINT_JSON_DEPTH = 8
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
TERMINAL_OUTCOMES = frozenset({"completed", "unchanged", "skipped", "failed", "cancelled"})


def request_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class CompletedCheckpointItem:
    video_id: str
    captured_sha256: str
    normalized_sha256: str
    outcome: str
    attempts: int
    captured_path: str
    normalized_path: str
    resolved_locator: str
    title: str | None
    channel: str | None
    published_at: str | None
    language: str
    caption_kind: str
    caption_format: str
    caption_name: str | None
    playlist_id: str | None
    source_position: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "video_id": self.video_id,
            "captured_sha256": self.captured_sha256,
            "normalized_sha256": self.normalized_sha256,
            "outcome": self.outcome,
            "attempts": self.attempts,
            "captured_path": self.captured_path,
            "normalized_path": self.normalized_path,
            "resolved_locator": self.resolved_locator,
            "title": self.title,
            "channel": self.channel,
            "published_at": self.published_at,
            "language": self.language,
            "caption_kind": self.caption_kind,
            "caption_format": self.caption_format,
            "caption_name": self.caption_name,
            "playlist_id": self.playlist_id,
            "source_position": self.source_position,
        }


@dataclass(frozen=True)
class YouTubeCheckpoint:
    request_fingerprint: str
    adapter_version: str
    contract_version: str
    playlist_id: str
    observed_video_ids: tuple[str, ...]
    completed: tuple[CompletedCheckpointItem, ...]
    terminal_outcomes: dict[str, str]
    attempts: dict[str, int]
    pending_video_ids: tuple[str, ...]
    continuation: str | None
    last_successful_boundary: str
    run_id: str
    package_id: str
    prior_run_ids: tuple[str, ...] = ()
    prior_package_ids: tuple[str, ...] = ()
    schema_version: str = CHECKPOINT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_fingerprint": self.request_fingerprint,
            "adapter_version": self.adapter_version,
            "contract_version": self.contract_version,
            "playlist_id": self.playlist_id,
            "bounded_discovery": {"video_ids": list(self.observed_video_ids)},
            "completed": [item.as_dict() for item in self.completed],
            "terminal_outcomes": self.terminal_outcomes,
            "attempts": self.attempts,
            "pending_video_ids": list(self.pending_video_ids),
            "continuation": self.continuation,
            "last_successful_boundary": self.last_successful_boundary,
            "run_id": self.run_id,
            "package_id": self.package_id,
            "prior_run_ids": list(self.prior_run_ids),
            "prior_package_ids": list(self.prior_package_ids),
        }


def save_checkpoint(checkpoint: YouTubeCheckpoint, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    data = canonical_json_bytes(checkpoint.as_dict())
    if len(data) > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint byte limit exceeded")
    temporary.write_bytes(data)
    temporary.replace(destination)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_depth(value: object, depth: int = 1) -> int:
    if isinstance(value, dict):
        return max((_json_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value), default=depth)
    return depth


def _read_bounded(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("checkpoint artifact is not a regular file")
    try:
        if path.stat().st_size > limit:
            raise ValueError("checkpoint byte limit exceeded")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ValueError("checkpoint read failure") from exc
    if len(data) > limit:
        raise ValueError("checkpoint byte limit exceeded")
    return data


def _artifact_path(checkpoint_path: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    owned_root = f"{checkpoint_path.stem}.data"
    if (
        not relative
        or "\\" in relative
        or pure.is_absolute()
        or ".." in pure.parts
        or pure.as_posix() != relative
        or not pure.parts
        or pure.parts[0] != owned_root
    ):
        raise ValueError("unsafe checkpoint artifact path")
    return checkpoint_path.parent.joinpath(*pure.parts)


def save_checkpoint_artifacts(
    checkpoint_path: Path,
    *,
    video_id: str,
    captured: bytes,
    normalized: bytes,
) -> tuple[str, str]:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("unsafe checkpoint video ID")
    if len(captured) > MAX_CAPTION_BYTES or len(normalized) > MAX_CAPTION_BYTES:
        raise ValueError("checkpoint artifact byte limit exceeded")
    root_name = f"{checkpoint_path.stem}.data"
    relative_root = PurePosixPath(root_name, f"youtube-video-{video_id}")
    captured_relative = (relative_root / "captured.vtt").as_posix()
    normalized_relative = (relative_root / "normalized.md").as_posix()
    for relative, data in (
        (captured_relative, captured),
        (normalized_relative, normalized),
    ):
        destination = _artifact_path(checkpoint_path, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
        temporary.write_bytes(data)
        temporary.replace(destination)
    return captured_relative, normalized_relative


def read_completed_artifacts(
    checkpoint_path: Path, item: CompletedCheckpointItem
) -> tuple[bytes, bytes]:
    captured = _read_bounded(_artifact_path(checkpoint_path, item.captured_path), MAX_CAPTION_BYTES)
    normalized = _read_bounded(
        _artifact_path(checkpoint_path, item.normalized_path), MAX_CAPTION_BYTES
    )
    if _digest(captured) != item.captured_sha256 or _digest(normalized) != item.normalized_sha256:
        raise ValueError("checkpoint artifact digest mismatch")
    return captured, normalized


def copy_completed_item(
    source_checkpoint: Path,
    destination_checkpoint: Path,
    item: CompletedCheckpointItem,
) -> CompletedCheckpointItem:
    captured, normalized = read_completed_artifacts(source_checkpoint, item)
    captured_path, normalized_path = save_checkpoint_artifacts(
        destination_checkpoint,
        video_id=item.video_id,
        captured=captured,
        normalized=normalized,
    )
    return CompletedCheckpointItem(
        item.video_id,
        item.captured_sha256,
        item.normalized_sha256,
        item.outcome,
        item.attempts,
        captured_path,
        normalized_path,
        item.resolved_locator,
        item.title,
        item.channel,
        item.published_at,
        item.language,
        item.caption_kind,
        item.caption_format,
        item.caption_name,
        item.playlist_id,
        item.source_position,
    )


def load_checkpoint(
    path: Path,
    *,
    expected_fingerprint: str,
    expected_adapter_version: str | None = None,
    expected_contract_version: str | None = None,
) -> YouTubeCheckpoint:
    try:
        raw: Any = json.loads(_read_bounded(path, MAX_CHECKPOINT_BYTES))
        if not isinstance(raw, dict) or raw.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported checkpoint schema")
        if raw.get("request_fingerprint") != expected_fingerprint:
            raise ValueError("checkpoint request fingerprint mismatch")
        if _json_depth(raw) > MAX_CHECKPOINT_JSON_DEPTH:
            raise ValueError("checkpoint JSON depth limit exceeded")
        discovery = raw["bounded_discovery"]
        if not isinstance(discovery, dict) or set(discovery) != {"video_ids"}:
            raise TypeError
        if not isinstance(raw["completed"], list):
            raise TypeError
        completed = tuple(CompletedCheckpointItem(**item) for item in raw["completed"])
        if not isinstance(raw["attempts"], dict) or any(
            not isinstance(key, str) or type(value) is not int
            for key, value in raw["attempts"].items()
        ):
            raise TypeError
        checkpoint = YouTubeCheckpoint(
            request_fingerprint=raw["request_fingerprint"],
            adapter_version=raw["adapter_version"],
            contract_version=raw["contract_version"],
            playlist_id=raw["playlist_id"],
            observed_video_ids=tuple(discovery["video_ids"]),
            completed=completed,
            terminal_outcomes=dict(raw["terminal_outcomes"]),
            attempts=dict(raw["attempts"]),
            pending_video_ids=tuple(raw["pending_video_ids"]),
            continuation=raw.get("continuation"),
            last_successful_boundary=raw["last_successful_boundary"],
            run_id=raw["run_id"],
            package_id=raw["package_id"],
            prior_run_ids=tuple(raw["prior_run_ids"]),
            prior_package_ids=tuple(raw["prior_package_ids"]),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("corrupt checkpoint") from exc
    if (
        any(
            not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id)
            for video_id in checkpoint.observed_video_ids
        )
        or any(not isinstance(video_id, str) for video_id in checkpoint.pending_video_ids)
        or not isinstance(checkpoint.terminal_outcomes, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in checkpoint.terminal_outcomes.items()
        )
        or not isinstance(checkpoint.continuation, (str, type(None)))
        or (isinstance(checkpoint.continuation, str) and len(checkpoint.continuation) > 4096)
    ):
        raise ValueError("corrupt checkpoint")
    observed = set(checkpoint.observed_video_ids)
    completed_ids = {item.video_id for item in checkpoint.completed}
    pending = set(checkpoint.pending_video_ids)
    if (
        not checkpoint.playlist_id
        or len(checkpoint.playlist_id) > 200
        or not checkpoint.last_successful_boundary
        or len(checkpoint.observed_video_ids) > MAX_COLLECTION_ITEMS
        or len(observed) != len(checkpoint.observed_video_ids)
        or len(completed_ids) != len(checkpoint.completed)
        or pending - observed
        or completed_ids - observed
        or pending & completed_ids
        or set(checkpoint.terminal_outcomes) - observed
        or set(checkpoint.attempts) - observed
        or any(value not in TERMINAL_OUTCOMES for value in checkpoint.terminal_outcomes.values())
        or any(value <= 0 or value > 10 for value in checkpoint.attempts.values())
        or any(
            item.attempts <= 0
            or item.attempts > 10
            or item.outcome not in TERMINAL_OUTCOMES
            or not DIGEST_RE.fullmatch(item.captured_sha256)
            or not DIGEST_RE.fullmatch(item.normalized_sha256)
            or not VIDEO_ID_RE.fullmatch(item.video_id)
            or not isinstance(item.resolved_locator, str)
            or not item.resolved_locator
            or len(item.resolved_locator) > 4096
            or any(
                value is not None and (not isinstance(value, str) or len(value) > 4096)
                for value in (item.title, item.channel, item.published_at, item.caption_name)
            )
            or not isinstance(item.language, str)
            or not item.language
            or len(item.language) > 64
            or item.caption_kind not in {"creator", "automatic"}
            or not isinstance(item.caption_format, str)
            or not item.caption_format
            or len(item.caption_format) > 32
            or (
                item.playlist_id is not None
                and (not isinstance(item.playlist_id, str) or len(item.playlist_id) > 200)
            )
            or (
                item.source_position is not None
                and (type(item.source_position) is not int or item.source_position <= 0)
            )
            for item in checkpoint.completed
        )
        or not checkpoint.run_id
        or not checkpoint.package_id
        or len(checkpoint.run_id) > 200
        or len(checkpoint.package_id) > 200
        or len(set(checkpoint.prior_run_ids)) != len(checkpoint.prior_run_ids)
        or len(set(checkpoint.prior_package_ids)) != len(checkpoint.prior_package_ids)
        or any(
            not isinstance(value, str) or not value or len(value) > 200
            for value in checkpoint.prior_run_ids
        )
        or any(
            not isinstance(value, str) or not value or len(value) > 200
            for value in checkpoint.prior_package_ids
        )
    ):
        raise ValueError("corrupt checkpoint")
    if (
        expected_adapter_version is not None
        and checkpoint.adapter_version != expected_adapter_version
    ):
        raise ValueError("checkpoint adapter version mismatch")
    if (
        expected_contract_version is not None
        and checkpoint.contract_version != expected_contract_version
    ):
        raise ValueError("checkpoint contract version mismatch")
    for item in checkpoint.completed:
        read_completed_artifacts(path, item)
    return checkpoint


def reconcile_video_ids(
    checkpoint: YouTubeCheckpoint, rediscovered: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    completed = {item.video_id for item in checkpoint.completed}
    preserved = tuple(video_id for video_id in rediscovered if video_id in completed)
    pending = tuple(video_id for video_id in rediscovered if video_id not in completed)
    return preserved, pending
