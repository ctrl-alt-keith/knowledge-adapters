"""Bounded YouTube production through the canonical Source Package core."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from knowledge_adapters.source_package import (
    AdapterIdentity,
    Artifact,
    ItemOutcome,
    PackageBuilder,
    PackageItem,
    VerificationResult,
    canonical_json_bytes,
    verify_package,
)

from .captions import select_caption
from .checkpoint import (
    CompletedCheckpointItem,
    YouTubeCheckpoint,
    copy_completed_item,
    load_checkpoint,
    reconcile_video_ids,
    request_fingerprint,
    save_checkpoint,
    save_checkpoint_artifacts,
)
from .client import YouTubeClient
from .config import YOUTUBE_EXTENSION, NoCaptionOutcome, ScopeKind, YouTubeOptions
from .models import (
    CaptionKind,
    PlaylistEntry,
    ProviderFailure,
    ProviderFailureCategory,
    VideoObservation,
)
from .normalize import (
    NORMALIZER_NAME,
    NORMALIZER_VERSION,
    CaptionNormalizationError,
    normalize_webvtt,
)

ADAPTER_VERSION = "0.1.0"
CONTRACT_VERSION = "1.0.0"


class CollectionProgressBlocked(RuntimeError):
    """Partial/resumed sealing awaits a canonical collection-progress invariant."""


@dataclass(frozen=True)
class ProductionResult:
    package_path: Path
    content_address: str
    verification: VerificationResult


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _request_fingerprint(request: dict[str, object]) -> str:
    stable = dict(request)
    for runtime_key in ("request_id", "output_location", "checkpoint_reference"):
        stable.pop(runtime_key, None)
    return request_fingerprint(stable)


def _ordered_entries(entries: tuple[PlaylistEntry, ...]) -> tuple[PlaylistEntry, ...]:
    return tuple(
        sorted(
            entries,
            key=lambda item: (
                item.position is None,
                item.position if item.position is not None else 2**63,
                item.video_id,
            ),
        )
    )


def _failure_mapping(category: ProviderFailureCategory) -> tuple[ItemOutcome, str, bool]:
    values = {
        ProviderFailureCategory.PRIVATE: (ItemOutcome.FAILED, "access-denied", False),
        ProviderFailureCategory.REMOVED: (ItemOutcome.FAILED, "provider-removed", False),
        ProviderFailureCategory.AGE_RESTRICTED: (
            ItemOutcome.FAILED,
            "access-restricted",
            False,
        ),
        ProviderFailureCategory.GEO_RESTRICTED: (
            ItemOutcome.FAILED,
            "geo-restricted",
            False,
        ),
        ProviderFailureCategory.UNAVAILABLE: (
            ItemOutcome.FAILED,
            "provider-unavailable",
            False,
        ),
        ProviderFailureCategory.TIMEOUT: (ItemOutcome.FAILED, "provider-transient", True),
        ProviderFailureCategory.THROTTLED: (ItemOutcome.FAILED, "provider-transient", True),
        ProviderFailureCategory.TRANSIENT: (ItemOutcome.FAILED, "provider-transient", True),
        ProviderFailureCategory.CANCELLED: (
            ItemOutcome.CANCELLED,
            "operator-cancelled",
            False,
        ),
    }
    return values[category]


def _diagnostic(
    item_id: str, category: str, provider_code: str, attempts: int, retryable: bool
) -> Artifact:
    return Artifact(
        f"diagnostics/{item_id}.json",
        canonical_json_bytes(
            {
                "schema_version": "1.0.0",
                "category": category,
                "provider_code": provider_code[:120],
                "attempts": attempts,
                "retryable": retryable,
            }
        ),
        "diagnostic",
        "application/json",
    )


def _failure_item(
    entry: PlaylistEntry,
    *,
    playlist_id: str | None,
    requested_locator: str,
    failure: ProviderFailure,
    attempts: int,
) -> tuple[PackageItem, Artifact]:
    outcome, category, retryable = _failure_mapping(failure.category)
    item_id = f"youtube-video-{entry.video_id}"
    diagnostic = _diagnostic(item_id, category, failure.code, attempts, retryable)
    fields: dict[str, object] = {
        "requested_locator": requested_locator,
        "canonical_locator": f"https://www.youtube.com/watch?v={entry.video_id}",
        "provenance": {"provider": "youtube", "provider_resource_id": entry.video_id},
        "error": {"category": category, "attempts": attempts, "retryable": retryable},
        "diagnostics": [diagnostic.path],
        "extensions": {
            YOUTUBE_EXTENSION: {
                "provider_code": failure.code[:120],
                **({"playlist_id": playlist_id} if playlist_id else {}),
                **({"source_position": entry.position} if entry.position is not None else {}),
            }
        },
    }
    return PackageItem(item_id, "video", outcome, fields), diagnostic


def _completed_item(
    entry: PlaylistEntry,
    observation: VideoObservation,
    options: YouTubeOptions,
    playlist_id: str | None,
) -> tuple[PackageItem, tuple[Artifact, ...]]:
    item_id = f"youtube-video-{entry.video_id}"
    selection = select_caption(observation.captions, options)
    common: dict[str, object] = {
        "requested_locator": options.locator,
        "resolved_locator": observation.resolved_locator,
        "canonical_locator": f"https://www.youtube.com/watch?v={entry.video_id}",
        "provenance": {"provider": "youtube", "provider_resource_id": entry.video_id},
    }
    for key, value in (
        ("title", observation.title),
        ("creator", observation.channel),
        ("published_at", observation.published_at),
    ):
        if value is not None:
            common[key] = value
    relation = {
        **({"playlist_id": playlist_id} if playlist_id else {}),
        **({"source_position": entry.position} if entry.position is not None else {}),
    }
    candidate_summary = [
        {
            "language": candidate.language,
            "kind": candidate.kind.value,
            "format": candidate.format,
            **({"name": candidate.name} if candidate.name else {}),
        }
        for candidate in observation.caption_candidates
    ]
    if playlist_id:
        common["parents"] = [
            {
                "resource_kind": "collection",
                "canonical_locator": f"https://www.youtube.com/playlist?list={playlist_id}",
            }
        ]
    if selection is None:
        if options.no_caption_outcome is NoCaptionOutcome.SKIP:
            common["skip_reason"] = {
                "category": "captions-unavailable",
                "policy": options.caption_policy.value,
            }
            common["extensions"] = {
                YOUTUBE_EXTENSION: {**relation, "available_candidates": candidate_summary}
            }
            return PackageItem(item_id, "video", ItemOutcome.SKIPPED, common), ()
        failure = ProviderFailure(ProviderFailureCategory.UNAVAILABLE, "captions-unavailable")
        item, diagnostic = _failure_item(
            entry,
            playlist_id=playlist_id,
            requested_locator=options.locator,
            failure=failure,
            attempts=1,
        )
        return item, (diagnostic,)
    track = selection.track
    if track.format.lower() != "vtt":
        failure = ProviderFailure(ProviderFailureCategory.UNAVAILABLE, "normalization-unsupported")
        item, diagnostic = _failure_item(
            entry,
            playlist_id=playlist_id,
            requested_locator=options.locator,
            failure=failure,
            attempts=1,
        )
        fields = dict(item.fields)
        fields["error"] = {
            "category": "normalization-unsupported",
            "attempts": 1,
            "retryable": False,
        }
        youtube_evidence: dict[str, object] = {}
        extensions_value = fields.get("extensions")
        if isinstance(extensions_value, dict):
            youtube_value = extensions_value.get(YOUTUBE_EXTENSION)
            if isinstance(youtube_value, dict):
                youtube_evidence.update(youtube_value)
        youtube_evidence.update(
            {
                "available_candidates": candidate_summary,
                "selected_track": {
                    "language": track.language,
                    "kind": track.kind.value,
                    "format": track.format,
                    **({"name": track.name} if track.name else {}),
                },
            }
        )
        fields["extensions"] = {YOUTUBE_EXTENSION: youtube_evidence}
        diagnostic = _diagnostic(
            item.item_id, "normalization-unsupported", "unsupported-caption-format", 1, False
        )
        return PackageItem(item.item_id, item.resource_kind, item.outcome, fields), (diagnostic,)
    try:
        normalized = normalize_webvtt(track.data, automatic=track.kind is CaptionKind.AUTOMATIC)
    except CaptionNormalizationError:
        failure = ProviderFailure(ProviderFailureCategory.UNAVAILABLE, "normalization-malformed")
        item, diagnostic = _failure_item(
            entry,
            playlist_id=playlist_id,
            requested_locator=options.locator,
            failure=failure,
            attempts=1,
        )
        fields = dict(item.fields)
        fields["error"] = {
            "category": "normalization-malformed",
            "attempts": 1,
            "retryable": False,
        }
        diagnostic = _diagnostic(
            item.item_id, "normalization-malformed", "malformed-webvtt", 1, False
        )
        return PackageItem(item.item_id, item.resource_kind, item.outcome, fields), (diagnostic,)
    normalized_path = f"artifacts/{item_id}/normalized.md"
    artifacts = [Artifact(normalized_path, normalized.data, "normalized-content", "text/markdown")]
    raw_path: str | None = None
    if options.retain_raw_captions:
        raw_path = f"artifacts/{item_id}/captured.vtt"
        artifacts.append(
            Artifact(raw_path, track.data, f"{YOUTUBE_EXTENSION}/raw-caption", "text/vtt")
        )
    common.update(
        {
            "language": track.language,
            "artifacts": [artifact.path for artifact in artifacts],
            "captured_sha256": _digest(track.data),
            "normalized_sha256": _digest(normalized.data),
            "normalization": {
                "name": NORMALIZER_NAME,
                "version": NORMALIZER_VERSION,
                "transforms": list(normalized.transforms),
            },
            "extensions": {
                YOUTUBE_EXTENSION: {
                    **relation,
                    "caption_kind": track.kind.value,
                    "selected_track": {
                        "language": track.language,
                        "format": track.format,
                        **({"name": track.name} if track.name else {}),
                    },
                    "selection_reason": selection.reason,
                    "available_candidates": candidate_summary or list(selection.candidates),
                    **({"raw_caption_path": raw_path} if raw_path else {}),
                }
            },
        }
    )
    return PackageItem(item_id, "video", ItemOutcome.COMPLETED, common), tuple(artifacts)


def produce_package(
    options: YouTubeOptions,
    client: YouTubeClient,
    *,
    request_id: str,
    run_id: str,
    package_id: str,
    created_at: str,
    destination: Path,
    adapter_revision: str | None = None,
) -> ProductionResult:
    request = options.acquisition_request(request_id, destination)
    fingerprint = _request_fingerprint(request.as_dict())
    discovery = client.discover(options)
    entries = _ordered_entries(discovery.entries[: options.max_items])
    if options.checkpoint_input is not None:
        checkpoint = load_checkpoint(
            options.checkpoint_input,
            expected_fingerprint=fingerprint,
            expected_adapter_version=ADAPTER_VERSION,
            expected_contract_version=CONTRACT_VERSION,
        )
        rediscovered = tuple(entry.video_id for entry in entries)
        preserved_ids, pending_ids = reconcile_video_ids(checkpoint, rediscovered)
        completed_by_id = {item.video_id: item for item in checkpoint.completed}
        assert options.checkpoint_output is not None
        preserved = tuple(
            copy_completed_item(
                options.checkpoint_input,
                options.checkpoint_output,
                completed_by_id[video_id],
            )
            for video_id in preserved_ids
        )
        save_checkpoint(
            YouTubeCheckpoint(
                fingerprint,
                ADAPTER_VERSION,
                CONTRACT_VERSION,
                discovery.playlist_id or checkpoint.playlist_id,
                rediscovered,
                preserved,
                {item.video_id: item.outcome for item in preserved},
                {
                    video_id: checkpoint.attempts.get(video_id, 1)
                    for video_id in rediscovered
                    if video_id in checkpoint.attempts
                },
                pending_ids,
                discovery.continuation or checkpoint.continuation,
                "resume-reconciled",
            ),
            options.checkpoint_output,
        )
        raise CollectionProgressBlocked(
            "resumed sealing requires canonical builder-supported resume lineage"
        )
    if options.scope is ScopeKind.COLLECTION and (
        not discovery.exhausted
        or (options.batch_size is not None and options.batch_size < len(entries))
    ):
        if options.checkpoint_output is not None:
            completed: list[CompletedCheckpointItem] = []
            outcomes: dict[str, str] = {}
            checkpoint_attempts: dict[str, int] = {}
            batch_size = options.batch_size or 0
            for entry in entries[:batch_size]:
                checkpoint_attempts[entry.video_id] = 1
                try:
                    observation = client.enrich(entry.video_id, options)
                    item, artifacts = _completed_item(
                        entry, observation, options, discovery.playlist_id
                    )
                    outcomes[entry.video_id] = item.outcome.value
                    captured = item.fields.get("captured_sha256")
                    normalized = item.fields.get("normalized_sha256")
                    if (
                        item.outcome is ItemOutcome.COMPLETED
                        and isinstance(captured, str)
                        and isinstance(normalized, str)
                    ):
                        selection = select_caption(observation.captions, options)
                        normalized_artifact = next(
                            artifact
                            for artifact in artifacts
                            if artifact.role == "normalized-content"
                        )
                        assert selection is not None
                        captured_path, normalized_path = save_checkpoint_artifacts(
                            options.checkpoint_output,
                            video_id=entry.video_id,
                            captured=selection.track.data,
                            normalized=normalized_artifact.data,
                        )
                        completed.append(
                            CompletedCheckpointItem(
                                entry.video_id,
                                captured,
                                normalized,
                                item.outcome.value,
                                1,
                                captured_path,
                                normalized_path,
                            )
                        )
                except ProviderFailure as checkpoint_failure:
                    outcome, _, _ = _failure_mapping(checkpoint_failure.category)
                    outcomes[entry.video_id] = outcome.value
            save_checkpoint(
                YouTubeCheckpoint(
                    fingerprint,
                    ADAPTER_VERSION,
                    CONTRACT_VERSION,
                    discovery.playlist_id or "unknown",
                    tuple(entry.video_id for entry in entries),
                    tuple(completed),
                    outcomes,
                    checkpoint_attempts,
                    tuple(entry.video_id for entry in entries if entry.video_id not in outcomes),
                    discovery.continuation or f"batch-after:{batch_size}",
                    "bounded-discovery",
                ),
                options.checkpoint_output,
            )
        raise CollectionProgressBlocked(
            "partial collection sealing requires canonical collection progress"
        )
    builder = PackageBuilder(
        package_id=package_id,
        request=request,
        run_id=run_id,
        created_at=created_at,
        adapter=AdapterIdentity("youtube-source-package", ADAPTER_VERSION, adapter_revision),
        contract_version=CONTRACT_VERSION,
        boundary={
            "deterministic": (
                f"captured captions normalized by {NORMALIZER_NAME}/{NORMALIZER_VERSION}"
            ),
            "live": "discovery, metadata, and caption acquisition through yt-dlp",
        },
        extensions={YOUTUBE_EXTENSION: {"yt_dlp_version": client.version}},
    )
    for entry in entries:
        if not entry.available or entry.failure is not None:
            failure = ProviderFailure(
                entry.failure or ProviderFailureCategory.UNAVAILABLE,
                "playlist-member-unavailable",
            )
            item, diagnostic = _failure_item(
                entry,
                playlist_id=discovery.playlist_id,
                requested_locator=options.locator,
                failure=failure,
                attempts=1,
            )
            builder.add_item(item)
            builder.add_artifact(diagnostic)
            continue
        attempts = 0
        while True:
            attempts += 1
            try:
                observation = client.enrich(entry.video_id, options)
                item, artifacts = _completed_item(
                    entry, observation, options, discovery.playlist_id
                )
                builder.add_item(item)
                for artifact in artifacts:
                    builder.add_artifact(artifact)
                break
            except ProviderFailure as failure:
                _, _, retryable = _failure_mapping(failure.category)
                if retryable and attempts < options.retry.max_attempts:
                    continue
                item, diagnostic = _failure_item(
                    entry,
                    playlist_id=discovery.playlist_id,
                    requested_locator=options.locator,
                    failure=failure,
                    attempts=attempts,
                )
                builder.add_item(item)
                builder.add_artifact(diagnostic)
                break
    sealed = builder.seal(destination)
    if not sealed.ok or sealed.package_path is None or sealed.content_address is None:
        raise RuntimeError(sealed.error or "package sealing failed")
    verification = verify_package(sealed.package_path)
    if not verification.ok or verification.content_address != sealed.content_address:
        raise RuntimeError("sealed package failed public verification")
    return ProductionResult(sealed.package_path, sealed.content_address, verification)
