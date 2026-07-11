"""Bounded YouTube production through the canonical Source Package core."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from knowledge_adapters.source_package import (
    COLLECTION_PROGRESS_CAPABILITY,
    AdapterIdentity,
    Artifact,
    CollectionProgress,
    CollectionProgressState,
    ConsumerProfile,
    ItemOutcome,
    PackageBuilder,
    PackageItem,
    PackageLineage,
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
    read_completed_artifacts,
    reconcile_video_ids,
    request_fingerprint,
    save_checkpoint,
    save_checkpoint_artifacts,
)
from .client import YouTubeClient
from .config import YOUTUBE_EXTENSION, NoCaptionOutcome, ScopeKind, YouTubeOptions
from .models import (
    CaptionCandidate,
    CaptionKind,
    CaptionTrack,
    PlaylistEntry,
    ProviderFailure,
    ProviderFailureCategory,
    VideoObservation,
)
from .normalize import (
    NORMALIZER_NAME,
    NORMALIZER_VERSION,
    TRANSFORMS,
    CaptionNormalizationError,
    normalize_webvtt,
)

ADAPTER_VERSION = "0.1.0"
CONTRACT_VERSION = "1.0.0"


class CollectionProgressBlocked(RuntimeError):
    """Provider continuation cannot advance through bounded rediscovery safely."""


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


def _checkpointed_item(
    checkpoint_path: Path,
    cached: CompletedCheckpointItem,
    options: YouTubeOptions,
) -> tuple[PackageItem, tuple[Artifact, ...]]:
    captured, normalized = read_completed_artifacts(checkpoint_path, cached)
    if captured is None:
        item_id = f"youtube-video-{cached.video_id}"
        normalized_path = f"artifacts/{item_id}/normalized.md"
        artifact = Artifact(
            normalized_path, normalized, "normalized-content", "text/markdown"
        )
        fields: dict[str, object] = {
            "requested_locator": options.locator,
            "resolved_locator": cached.resolved_locator,
            "canonical_locator": f"https://www.youtube.com/watch?v={cached.video_id}",
            "provenance": {"provider": "youtube", "provider_resource_id": cached.video_id},
            "language": cached.language,
            "artifacts": [normalized_path],
            "captured_sha256": cached.captured_sha256,
            "normalized_sha256": cached.normalized_sha256,
            "normalization": {
                "name": NORMALIZER_NAME,
                "version": NORMALIZER_VERSION,
                "transforms": list(TRANSFORMS),
            },
            "extensions": {
                YOUTUBE_EXTENSION: {
                    **({"playlist_id": cached.playlist_id} if cached.playlist_id else {}),
                    **(
                        {"source_position": cached.source_position}
                        if cached.source_position is not None
                        else {}
                    ),
                    "caption_kind": cached.caption_kind,
                    "selected_track": {
                        "language": cached.language,
                        "format": cached.caption_format,
                        **({"name": cached.caption_name} if cached.caption_name else {}),
                    },
                    "selection_reason": "checkpoint-preserved-normalized-content",
                    "available_candidates": [
                        {
                            "language": cached.language,
                            "kind": cached.caption_kind,
                            "format": cached.caption_format,
                            **({"name": cached.caption_name} if cached.caption_name else {}),
                        }
                    ],
                }
            },
        }
        for key, value in (
            ("title", cached.title),
            ("creator", cached.channel),
            ("published_at", cached.published_at),
        ):
            if value is not None:
                fields[key] = value
        if cached.playlist_id:
            fields["parents"] = [
                {
                    "resource_kind": "collection",
                    "canonical_locator": (
                        f"https://www.youtube.com/playlist?list={cached.playlist_id}"
                    ),
                }
            ]
        return PackageItem(item_id, "video", ItemOutcome.UNCHANGED, fields), (artifact,)
    kind = CaptionKind(cached.caption_kind)
    observation = VideoObservation(
        cached.video_id,
        cached.resolved_locator,
        cached.title,
        cached.channel,
        cached.published_at,
        (
            CaptionTrack(
                cached.language,
                kind,
                cached.caption_format,
                captured,
                cached.caption_name,
            ),
        ),
        (
            CaptionCandidate(
                cached.language,
                kind,
                cached.caption_format,
                cached.caption_name,
            ),
        ),
    )
    entry = PlaylistEntry(cached.video_id, cached.source_position)
    item, artifacts = _completed_item(entry, observation, options, cached.playlist_id)
    normalized_artifact = next(
        artifact for artifact in artifacts if artifact.role == "normalized-content"
    )
    if normalized_artifact.data != normalized:
        raise ValueError("checkpoint normalization replay mismatch")
    return (
        PackageItem(item.item_id, item.resource_kind, ItemOutcome.UNCHANGED, item.fields),
        artifacts,
    )


def _cache_completed(
    checkpoint_path: Path,
    entry: PlaylistEntry,
    observation: VideoObservation,
    options: YouTubeOptions,
    item: PackageItem,
    artifacts: tuple[Artifact, ...],
    *,
    attempts: int,
    playlist_id: str | None,
) -> CompletedCheckpointItem | None:
    if item.outcome is not ItemOutcome.COMPLETED:
        return None
    selection = select_caption(observation.captions, options)
    if selection is None:
        return None
    normalized = next(
        artifact.data for artifact in artifacts if artifact.role == "normalized-content"
    )
    captured_path, normalized_path = save_checkpoint_artifacts(
        checkpoint_path,
        video_id=entry.video_id,
        captured=selection.track.data if options.retain_raw_captions else None,
        normalized=normalized,
    )
    return CompletedCheckpointItem(
        entry.video_id,
        _digest(selection.track.data),
        _digest(normalized),
        item.outcome.value,
        attempts,
        captured_path,
        normalized_path,
        observation.resolved_locator,
        observation.title,
        observation.channel,
        observation.published_at,
        selection.track.language,
        selection.track.kind.value,
        selection.track.format,
        selection.track.name,
        playlist_id,
        entry.position,
    )


def _producer_profile(options: YouTubeOptions) -> ConsumerProfile:
    item_bound = max(1, options.max_items)
    return ConsumerProfile(
        identifier="youtube-producer-v1",
        supported_capabilities=(COLLECTION_PROGRESS_CAPABILITY,),
        max_json_depth=32,
        max_package_entries=item_bound * 8 + 10,
        max_item_records=item_bound,
        max_artifacts=item_bound * 4 + 1,
        max_diagnostics=item_bound,
        max_file_bytes=max(16 * 1024 * 1024, options.max_caption_bytes),
        max_aggregate_bytes=512 * 1024 * 1024,
        max_path_length=1024,
        max_path_components=16,
    )


def _assert_verified_handoff(
    verification: VerificationResult,
    *,
    package_id: str,
    run_id: str,
    expected_progress: CollectionProgress | None,
    expected_items: tuple[PackageItem, ...],
    expected_artifacts: tuple[Artifact, ...],
) -> None:
    claims = verification.verified_claims
    if not verification.ok or claims is None or claims.totals is None:
        raise RuntimeError("sealed package failed public verification")
    if (
        verification.consumer_profile != "youtube-producer-v1"
        or claims.package_id != package_id
        or claims.run_id != run_id
        or claims.collection_progress != expected_progress
        or claims.totals.item_records != len(expected_items)
    ):
        raise RuntimeError("verified package summary does not match producer handoff")
    dispositions = {item.item_id: item for item in claims.item_dispositions}
    if set(dispositions) != {item.item_id for item in expected_items}:
        raise RuntimeError("verified item summary does not match producer handoff")
    for expected_item in expected_items:
        disposition = dispositions[expected_item.item_id]
        provenance = expected_item.fields.get("provenance")
        expected_provider_id = (
            provenance.get("provider_resource_id") if isinstance(provenance, dict) else None
        )
        if (
            disposition.outcome != expected_item.outcome.value
            or disposition.provider != "youtube"
            or disposition.provider_resource_id != expected_provider_id
        ):
            raise RuntimeError("verified item disposition does not match producer handoff")
    inventory = {artifact.path: artifact for artifact in claims.artifact_inventory}
    for expected_artifact in expected_artifacts:
        verified = inventory.get(expected_artifact.path)
        if (
            verified is None
            or verified.role != expected_artifact.role
            or verified.media_type != expected_artifact.media_type
            or verified.bytes != len(expected_artifact.data)
            or verified.sha256 != _digest(expected_artifact.data)
        ):
            raise RuntimeError("verified artifact summary does not match producer handoff")


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
    is_collection = options.scope is ScopeKind.COLLECTION
    checkpoint = None
    preserved_checkpoint_items: list[CompletedCheckpointItem] = []
    package_items: list[PackageItem] = []
    package_artifacts: list[Artifact] = []
    attempts_by_id: dict[str, int] = {}
    pending_entries = list(entries)
    lineage = None

    if options.checkpoint_input is not None:
        checkpoint = load_checkpoint(
            options.checkpoint_input,
            expected_fingerprint=fingerprint,
            expected_adapter_version=ADAPTER_VERSION,
            expected_contract_version="1.1.0",
            expected_retain_raw_captions=options.retain_raw_captions,
        )
        rediscovered = tuple(entry.video_id for entry in entries)
        preserved_ids, _ = reconcile_video_ids(checkpoint, rediscovered)
        completed_by_id = {item.video_id: item for item in checkpoint.completed}
        for video_id in preserved_ids:
            cached = completed_by_id[video_id]
            item, artifacts = _checkpointed_item(options.checkpoint_input, cached, options)
            package_items.append(item)
            package_artifacts.extend(artifacts)
            preserved_checkpoint_items.append(cached)
            attempts_by_id[video_id] = checkpoint.attempts.get(video_id, cached.attempts)
        preserved_set = set(preserved_ids)
        pending_entries = [entry for entry in entries if entry.video_id not in preserved_set]
        for entry in pending_entries:
            attempts_by_id[entry.video_id] = checkpoint.attempts.get(entry.video_id, 0)

    batch_limit = options.batch_size or len(pending_entries)
    attempted_entries = pending_entries[:batch_limit]
    unattempted_entries = pending_entries[batch_limit:]
    observations: dict[str, VideoObservation] = {}

    for entry in attempted_entries:
        prior_attempts = attempts_by_id.get(entry.video_id, 0)
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
                attempts=prior_attempts + 1,
            )
            package_items.append(item)
            package_artifacts.append(diagnostic)
            attempts_by_id[entry.video_id] = prior_attempts + 1
            continue
        run_attempts = 0
        while True:
            run_attempts += 1
            total_attempts = prior_attempts + run_attempts
            try:
                observation = client.enrich(entry.video_id, options)
                item, artifacts = _completed_item(
                    entry, observation, options, discovery.playlist_id
                )
                package_items.append(item)
                package_artifacts.extend(artifacts)
                observations[entry.video_id] = observation
                attempts_by_id[entry.video_id] = total_attempts
                break
            except ProviderFailure as failure:
                _, _, retryable = _failure_mapping(failure.category)
                if retryable and run_attempts < options.retry.max_attempts:
                    continue
                item, diagnostic = _failure_item(
                    entry,
                    playlist_id=discovery.playlist_id,
                    requested_locator=options.locator,
                    failure=failure,
                    attempts=total_attempts,
                )
                package_items.append(item)
                package_artifacts.append(diagnostic)
                attempts_by_id[entry.video_id] = total_attempts
                break

    progress = None
    if is_collection:
        progress = CollectionProgress(
            CollectionProgressState.CONTINUATION_REMAINING
            if unattempted_entries or not discovery.exhausted
            else CollectionProgressState.EXHAUSTED
        )
        if (
            progress.state is CollectionProgressState.CONTINUATION_REMAINING
            and not unattempted_entries
            and not discovery.exhausted
        ):
            raise CollectionProgressBlocked(
                "provider continuation is not actionable through bounded rediscovery"
            )

    if checkpoint is not None:
        prior_run_ids = tuple((*checkpoint.prior_run_ids, checkpoint.run_id))
        prior_package_ids = tuple((*checkpoint.prior_package_ids, checkpoint.package_id))
        lineage = PackageLineage(
            resumes_run_id=checkpoint.run_id,
            prior_run_ids=prior_run_ids,
            prior_package_ids=prior_package_ids,
            reconciliation_summary={
                "reused": len(preserved_checkpoint_items),
                "dropped": len(checkpoint.completed) - len(preserved_checkpoint_items),
                "acquired": len(observations),
                "pending": len(unattempted_entries),
            },
            final_attempt_counts=attempts_by_id,
        )

    contract_version = "1.1.0" if is_collection else CONTRACT_VERSION
    builder = PackageBuilder(
        package_id=package_id,
        request=request,
        run_id=run_id,
        created_at=created_at,
        adapter=AdapterIdentity("youtube-source-package", ADAPTER_VERSION, adapter_revision),
        contract_version=contract_version,
        boundary={
            "deterministic": (
                f"captured captions normalized by {NORMALIZER_NAME}/{NORMALIZER_VERSION}"
            ),
            "live": "discovery, metadata, and caption acquisition through yt-dlp",
        },
        collection_progress=progress,
        lineage=lineage,
        extensions={YOUTUBE_EXTENSION: {"yt_dlp_version": client.version}},
    )
    for item in package_items:
        builder.add_item(item)
    for artifact in package_artifacts:
        builder.add_artifact(artifact)
    sealed = builder.seal(destination)
    if not sealed.ok or sealed.package_path is None or sealed.content_address is None:
        raise RuntimeError(sealed.error or "package sealing failed")
    verification = verify_package(sealed.package_path, profile=_producer_profile(options))
    if verification.content_address != sealed.content_address:
        raise RuntimeError("verified content address does not match sealed package")
    _assert_verified_handoff(
        verification,
        package_id=package_id,
        run_id=run_id,
        expected_progress=progress,
        expected_items=tuple(package_items),
        expected_artifacts=tuple(package_artifacts),
    )

    if is_collection and options.checkpoint_output is not None:
        output_checkpoint = options.checkpoint_output
        cached_items: list[CompletedCheckpointItem] = []
        if checkpoint is not None and options.checkpoint_input is not None:
            cached_items.extend(
                copy_completed_item(options.checkpoint_input, output_checkpoint, item)
                for item in preserved_checkpoint_items
            )
        items_by_id = {item.item_id.removeprefix("youtube-video-"): item for item in package_items}
        artifacts_by_item = {
            video_id: tuple(
                artifact
                for artifact in package_artifacts
                if artifact.path.startswith(f"artifacts/youtube-video-{video_id}/")
            )
            for video_id in observations
        }
        entries_by_id = {entry.video_id: entry for entry in attempted_entries}
        for video_id, observation in observations.items():
            cached_result = _cache_completed(
                output_checkpoint,
                entries_by_id[video_id],
                observation,
                options,
                items_by_id[video_id],
                artifacts_by_item[video_id],
                attempts=attempts_by_id[video_id],
                playlist_id=discovery.playlist_id,
            )
            if cached_result is not None:
                cached_items.append(cached_result)
        save_checkpoint(
            YouTubeCheckpoint(
                fingerprint,
                ADAPTER_VERSION,
                contract_version,
                discovery.playlist_id or "unknown",
                tuple(entry.video_id for entry in entries),
                tuple(cached_items),
                {
                    item.item_id.removeprefix("youtube-video-"): item.outcome.value
                    for item in package_items
                },
                attempts_by_id,
                tuple(entry.video_id for entry in unattempted_entries),
                discovery.continuation,
                "package-verified",
                run_id,
                package_id,
                options.retain_raw_captions,
                tuple((*checkpoint.prior_run_ids, checkpoint.run_id)) if checkpoint else (),
                (
                    tuple((*checkpoint.prior_package_ids, checkpoint.package_id))
                    if checkpoint
                    else ()
                ),
            ),
            output_checkpoint,
        )
    return ProductionResult(sealed.package_path, sealed.content_address, verification)
