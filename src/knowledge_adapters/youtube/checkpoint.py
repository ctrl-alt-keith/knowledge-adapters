"""Bounded mutable checkpoint state outside Source Packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_adapters.source_package import canonical_json_bytes

CHECKPOINT_SCHEMA_VERSION = "1.0.0"
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

    def as_dict(self) -> dict[str, object]:
        return {
            "video_id": self.video_id,
            "captured_sha256": self.captured_sha256,
            "normalized_sha256": self.normalized_sha256,
            "outcome": self.outcome,
            "attempts": self.attempts,
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
        }


def save_checkpoint(checkpoint: YouTubeCheckpoint, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    temporary.write_bytes(canonical_json_bytes(checkpoint.as_dict()))
    temporary.replace(destination)


def load_checkpoint(
    path: Path,
    *,
    expected_fingerprint: str,
    expected_adapter_version: str | None = None,
    expected_contract_version: str | None = None,
) -> YouTubeCheckpoint:
    try:
        raw: Any = json.loads(path.read_bytes())
        if not isinstance(raw, dict) or raw.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported checkpoint schema")
        if raw.get("request_fingerprint") != expected_fingerprint:
            raise ValueError("checkpoint request fingerprint mismatch")
        discovery = raw["bounded_discovery"]
        completed = tuple(CompletedCheckpointItem(**item) for item in raw["completed"])
        checkpoint = YouTubeCheckpoint(
            request_fingerprint=raw["request_fingerprint"],
            adapter_version=raw["adapter_version"],
            contract_version=raw["contract_version"],
            playlist_id=raw["playlist_id"],
            observed_video_ids=tuple(discovery["video_ids"]),
            completed=completed,
            terminal_outcomes=dict(raw["terminal_outcomes"]),
            attempts={key: int(value) for key, value in raw["attempts"].items()},
            pending_video_ids=tuple(raw["pending_video_ids"]),
            continuation=raw.get("continuation"),
            last_successful_boundary=raw["last_successful_boundary"],
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("corrupt checkpoint") from exc
    observed = set(checkpoint.observed_video_ids)
    completed_ids = {item.video_id for item in checkpoint.completed}
    pending = set(checkpoint.pending_video_ids)
    if (
        not checkpoint.playlist_id
        or len(checkpoint.playlist_id) > 200
        or not checkpoint.last_successful_boundary
        or len(checkpoint.observed_video_ids) > 10_000
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
            for item in checkpoint.completed
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
    return checkpoint


def reconcile_video_ids(
    checkpoint: YouTubeCheckpoint, rediscovered: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    completed = {item.video_id for item in checkpoint.completed}
    preserved = tuple(video_id for video_id in rediscovered if video_id in completed)
    pending = tuple(video_id for video_id in rediscovered if video_id not in completed)
    return preserved, pending
