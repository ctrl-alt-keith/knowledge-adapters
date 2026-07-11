from __future__ import annotations

import hashlib
import io
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from knowledge_adapters.source_package import (
    CollectionProgress,
    CollectionProgressState,
    verify_package,
)
from knowledge_adapters.youtube import (
    BaseLanguageFallback,
    CaptionPolicy,
    CollectionProgressBlocked,
    NoCaptionOutcome,
    RetryPolicy,
    ScopeKind,
    YouTubeOptions,
    produce_package,
)
from knowledge_adapters.youtube.captions import select_caption
from knowledge_adapters.youtube.checkpoint import (
    MAX_CHECKPOINT_BYTES,
    CompletedCheckpointItem,
    YouTubeCheckpoint,
    load_checkpoint,
    reconcile_video_ids,
    request_fingerprint,
    save_checkpoint,
    save_checkpoint_artifacts,
)
from knowledge_adapters.youtube.client import YtDlpClient
from knowledge_adapters.youtube.models import (
    CaptionKind,
    CaptionTrack,
    Discovery,
    PlaylistEntry,
    ProviderFailure,
    ProviderFailureCategory,
    VideoObservation,
)
from knowledge_adapters.youtube.normalize import CaptionNormalizationError, normalize_webvtt

FIXTURES = Path(__file__).parents[1] / "fixtures" / "youtube"
VIDEO = "https://www.youtube.com/watch?v=video_001"
PLAYLIST = "https://www.youtube.com/playlist?list=playlist_001"


class FakeClient:
    version = "fixture-2026.07"

    def __init__(
        self,
        discovery: Discovery,
        videos: dict[
            str,
            VideoObservation | ProviderFailure | list[VideoObservation | ProviderFailure],
        ],
    ) -> None:
        self.discovery = discovery
        self.videos = videos
        self.calls: list[str] = []

    def discover(self, options: YouTubeOptions) -> Discovery:
        del options
        return self.discovery

    def enrich(self, video_id: str, options: YouTubeOptions) -> VideoObservation:
        del options
        self.calls.append(video_id)
        value = self.videos[video_id]
        if isinstance(value, list):
            current = value.pop(0)
        else:
            current = value
        if isinstance(current, ProviderFailure):
            raise current
        return current


def creator_track(language: str = "en") -> CaptionTrack:
    return CaptionTrack(
        language, CaptionKind.CREATOR, "vtt", (FIXTURES / "creator-en.vtt").read_bytes()
    )


def observed_automatic_track() -> CaptionTrack:
    return CaptionTrack(
        "en",
        CaptionKind.AUTOMATIC,
        "vtt",
        (FIXTURES / "automatic-timing-blank-text.vtt").read_bytes(),
    )


def video(video_id: str, *tracks: CaptionTrack) -> VideoObservation:
    return VideoObservation(
        video_id,
        f"https://www.youtube.com/watch?v={video_id}",
        f"Title {video_id}",
        "Fixture Channel",
        "20260710",
        tuple(tracks),
    )


def single_client(*tracks: CaptionTrack) -> FakeClient:
    discovery = Discovery(VIDEO, VIDEO, None, (PlaylistEntry("video_001", 1),), True)
    return FakeClient(discovery, {"video_001": video("video_001", *tracks)})


def options(**changes: object) -> YouTubeOptions:
    value = YouTubeOptions(VIDEO, ScopeKind.RESOURCE, 1)
    return replace(value, **changes)  # type: ignore[arg-type]


def produce(tmp_path: Path, client: FakeClient, opts: YouTubeOptions | None = None) -> Path:
    destination = tmp_path / "package"
    result = produce_package(
        opts or options(),
        client,
        request_id="request-fixture",
        run_id="run-fixture",
        package_id="package-fixture",
        created_at="2026-07-10T00:00:00Z",
        destination=destination,
        adapter_revision="fixture-revision",
    )
    assert result.verification.ok
    return destination


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"max_items": 0}, "between"),
        ({"max_items": 2}, "max_items=1"),
        ({"batch_size": 0}, "batch_size"),
        ({"languages": ()}, "language"),
        ({"languages": ("en", "en")}, "unique"),
    ],
)
def test_invalid_bounded_configuration(change: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(options(), **change)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "locator",
    [
        "http://www.youtube.com/watch?v=video_001",
        "https://example.test/watch?v=video_001",
        "https://user:secret@www.youtube.com/watch?v=video_001",
        "https://www.youtube.com/watch?v=video_001&token=secret",
        "https://www.youtube.com/watch?v=video_001&list=playlist_001",
    ],
)
def test_rejects_unsupported_ambiguous_or_secret_locators(locator: str) -> None:
    with pytest.raises(ValueError):
        YouTubeOptions(locator, ScopeKind.RESOURCE, 1)


def test_caption_selection_policy_and_language_preference() -> None:
    tracks = (
        CaptionTrack("en", CaptionKind.AUTOMATIC, "vtt", b"auto"),
        CaptionTrack("fr", CaptionKind.CREATOR, "vtt", b"creator"),
    )
    creator_first = select_caption(
        tracks,
        options(languages=("en", "fr"), caption_policy=CaptionPolicy.CREATOR_THEN_AUTOMATIC),
    )
    language_first = select_caption(
        tracks,
        options(languages=("en", "fr"), caption_policy=CaptionPolicy.AUTOMATIC_ALLOWED),
    )
    assert creator_first is not None and creator_first.track.language == "fr"
    assert language_first is not None and language_first.track.language == "en"


def test_explicit_base_language_fallback() -> None:
    track = CaptionTrack("en-US", CaptionKind.CREATOR, "vtt", b"x")
    assert select_caption((track,), options(languages=("en",))) is None
    selected = select_caption(
        (track,),
        options(languages=("en",), base_language_fallback=BaseLanguageFallback.ENABLED),
    )
    assert selected is not None and "base-language-fallback" in selected.reason


def test_creator_webvtt_normalization_is_exact() -> None:
    result = normalize_webvtt((FIXTURES / "creator-en.vtt").read_bytes(), automatic=False)
    assert result.data == b"Hello from the creator.\n\n**Ada:** Welcome aboard.\n"


def test_automatic_rolling_cues_are_collapsed() -> None:
    result = normalize_webvtt((FIXTURES / "automatic-rolling.vtt").read_bytes(), automatic=True)
    assert result.data == b"Rolling captions settle.\n"


def test_automatic_timing_blank_text_shape_is_normalized_deterministically() -> None:
    data = (FIXTURES / "automatic-timing-blank-text.vtt").read_bytes()

    first = normalize_webvtt(data, automatic=True)
    second = normalize_webvtt(data, automatic=True)

    assert first.data == b"Synthetic words extend\n\nFinal synthetic cue.\n"
    assert second.data == first.data


def test_timing_blank_text_shape_remains_invalid_for_creator_captions() -> None:
    with pytest.raises(CaptionNormalizationError, match="malformed WebVTT cue"):
        normalize_webvtt(
            (FIXTURES / "automatic-timing-blank-text.vtt").read_bytes(), automatic=False
        )


def test_standalone_text_without_timing_context_is_rejected() -> None:
    with pytest.raises(CaptionNormalizationError, match="malformed WebVTT cue"):
        normalize_webvtt(b"WEBVTT\n\nstandalone text\n", automatic=True)


def test_multiple_blanks_after_timing_remain_malformed() -> None:
    with pytest.raises(CaptionNormalizationError, match="malformed WebVTT cue"):
        normalize_webvtt(
            b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n\n\nstandalone text\n",
            automatic=True,
        )


def test_malformed_webvtt_is_rejected() -> None:
    with pytest.raises(CaptionNormalizationError):
        normalize_webvtt((FIXTURES / "malformed.vtt").read_bytes(), automatic=False)


def test_single_video_produces_publicly_verified_package_without_raw_caption(
    tmp_path: Path,
) -> None:
    package = produce(tmp_path, single_client(creator_track()))
    result = verify_package(package)
    assert result.ok and result.verified_claims is not None
    assert result.verified_claims.adapter is not None
    assert result.verified_claims.adapter.revision == "fixture-revision"
    manifest = json.loads((package / "package.json").read_bytes())
    assert manifest["extensions"]["org.ctrl-alt-keith.youtube"]["yt_dlp_version"] == (
        "fixture-2026.07"
    )
    files = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()}
    assert not any(path.endswith("captured.vtt") for path in files)
    all_bytes = b"".join(path.read_bytes() for path in package.rglob("*") if path.is_file())
    assert b"signature=" not in all_bytes and b"secret" not in all_bytes


def test_observed_automatic_shape_produces_verified_normalized_artifact(
    tmp_path: Path,
) -> None:
    package = produce(tmp_path, single_client(observed_automatic_track()))
    result = verify_package(package)
    normalized = package / "artifacts/youtube-video-video_001/normalized.md"

    assert result.ok
    assert normalized.read_bytes() == b"Synthetic words extend\n\nFinal synthetic cue.\n"
    assert not any(path.suffix == ".vtt" for path in package.rglob("*"))


def test_raw_caption_is_retained_only_by_opt_in(tmp_path: Path) -> None:
    package = produce(tmp_path, single_client(creator_track()), options(retain_raw_captions=True))
    raw = package / "artifacts/youtube-video-video_001/captured.vtt"
    assert raw.read_bytes() == (FIXTURES / "creator-en.vtt").read_bytes()


@pytest.mark.parametrize(
    ("no_caption", "expected"),
    [(NoCaptionOutcome.SKIP, "skipped"), (NoCaptionOutcome.FAIL, "failed")],
)
def test_configurable_no_caption_outcome(
    tmp_path: Path, no_caption: NoCaptionOutcome, expected: str
) -> None:
    package = produce(tmp_path, single_client(), options(no_caption_outcome=no_caption))
    item = json.loads((package / "items/youtube-video-video_001.json").read_bytes())
    assert item["outcome"] == expected


@pytest.mark.parametrize(
    ("category", "mapped", "attempts"),
    [
        (ProviderFailureCategory.PRIVATE, "access-denied", 1),
        (ProviderFailureCategory.REMOVED, "provider-removed", 1),
        (ProviderFailureCategory.AGE_RESTRICTED, "access-restricted", 1),
        (ProviderFailureCategory.GEO_RESTRICTED, "geo-restricted", 1),
        (ProviderFailureCategory.TIMEOUT, "provider-transient", 2),
        (ProviderFailureCategory.THROTTLED, "provider-transient", 2),
        (ProviderFailureCategory.TRANSIENT, "provider-transient", 2),
        (ProviderFailureCategory.CANCELLED, "operator-cancelled", 1),
    ],
)
def test_structured_failure_mapping(
    tmp_path: Path,
    category: ProviderFailureCategory,
    mapped: str,
    attempts: int,
) -> None:
    failure = ProviderFailure(category, f"fixture-{category.value}", retryable=attempts > 1)
    client = single_client(creator_track())
    client.videos["video_001"] = [failure for _ in range(attempts)]
    package = produce(tmp_path, client, options(retry=RetryPolicy(max_attempts=attempts)))
    item = json.loads((package / "items/youtube-video-video_001.json").read_bytes())
    assert item["error"] == {"attempts": attempts, "category": mapped, "retryable": attempts > 1}


def test_unsupported_caption_format_and_malformed_caption_are_failed(
    tmp_path: Path,
) -> None:
    unsupported = CaptionTrack("en", CaptionKind.CREATOR, "srt", b"unsupported")
    package = produce(tmp_path, single_client(unsupported))
    item = json.loads((package / "items/youtube-video-video_001.json").read_bytes())
    assert item["error"]["category"] == "normalization-unsupported"
    shutil.rmtree(package)
    malformed = CaptionTrack(
        "en", CaptionKind.CREATOR, "vtt", (FIXTURES / "malformed.vtt").read_bytes()
    )
    package = produce(tmp_path, single_client(malformed))
    item = json.loads((package / "items/youtube-video-video_001.json").read_bytes())
    assert item["error"]["category"] == "normalization-malformed"


def test_playlist_order_duplicate_missing_position_and_unavailable_member(
    tmp_path: Path,
) -> None:
    discovery = Discovery(
        PLAYLIST,
        PLAYLIST,
        "playlist_001",
        (
            PlaylistEntry("video_003", None),
            PlaylistEntry("video_002", 1, False, ProviderFailureCategory.UNAVAILABLE),
            PlaylistEntry("video_001", 1),
        ),
        True,
    )
    client = FakeClient(
        discovery,
        {
            "video_001": video("video_001", creator_track()),
            "video_003": video("video_003", creator_track()),
        },
    )
    opts = YouTubeOptions(PLAYLIST, ScopeKind.COLLECTION, 3)
    package = produce(tmp_path, client, opts)
    assert client.calls == ["video_001", "video_003"]
    failed = json.loads((package / "items/youtube-video-video_002.json").read_bytes())
    assert failed["error"]["category"] == "provider-unavailable"
    first = json.loads((package / "items/youtube-video-video_001.json").read_bytes())
    assert first["extensions"]["org.ctrl-alt-keith.youtube"]["source_position"] == 1


def test_partial_batch_seals_continuation_and_checkpoints_completed_bytes(
    tmp_path: Path,
) -> None:
    discovery = Discovery(
        PLAYLIST,
        PLAYLIST,
        "playlist_001",
        tuple(PlaylistEntry(f"video_00{index}", index) for index in range(1, 4)),
        True,
        "fixture-continuation",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    opts = YouTubeOptions(
        PLAYLIST,
        ScopeKind.COLLECTION,
        3,
        batch_size=2,
        checkpoint_output=checkpoint_path,
    )
    partial_videos = {
        "video_001": video("video_001", creator_track()),
        "video_002": video("video_002", creator_track()),
    }
    initial = produce_package(
        opts,
        FakeClient(discovery, dict(partial_videos)),
        request_id="request",
        run_id="run",
        package_id="package",
        created_at="2026-07-10T00:00:00Z",
        destination=tmp_path / "package",
    )
    assert initial.verification.verified_claims is not None
    assert initial.verification.verified_claims.collection_progress == CollectionProgress(
        CollectionProgressState.CONTINUATION_REMAINING
    )
    assert checkpoint_path.is_file() and (tmp_path / "package").is_dir()
    checkpoint_json = json.loads(checkpoint_path.read_bytes())
    assert [item["video_id"] for item in checkpoint_json["completed"]] == [
        "video_001",
        "video_002",
    ]
    assert checkpoint_json["pending_video_ids"] == ["video_003"]
    assert checkpoint_json["schema_version"] == "1.3.0"
    assert checkpoint_json["retain_raw_captions"] is False
    assert all(len(item["normalized_sha256"]) == 64 for item in checkpoint_json["completed"])
    assert all(item["captured_path"] is None for item in checkpoint_json["completed"])
    checkpoint_files = [path for path in tmp_path.rglob("*") if path.is_file()]
    checkpoint_bytes = b"".join(
        path.read_bytes()
        for path in checkpoint_files
        if path == checkpoint_path or ".data" in path.as_posix()
    )
    assert b"WEBVTT" not in checkpoint_bytes
    assert b"00:00:00.000 -->" not in checkpoint_bytes
    assert creator_track().data not in checkpoint_bytes
    assert not any(path.suffix == ".vtt" for path in checkpoint_files)
    assert not any(
        token in checkpoint_bytes.lower()
        for token in (b"signature=", b"cookie=", b"authorization=", b"credential=", b"token=")
    )
    resumed = replace(
        opts,
        checkpoint_input=checkpoint_path,
        checkpoint_output=tmp_path / "checkpoint-next.json",
    )
    changed_discovery = replace(
        discovery,
        entries=(
            PlaylistEntry("video_001", 1),
            PlaylistEntry("video_003", 2),
            PlaylistEntry("video_004", 3),
        ),
    )
    resume_client = FakeClient(
        changed_discovery,
        {
            "video_003": video("video_003", creator_track()),
            "video_004": video("video_004", creator_track()),
        },
    )
    resumed_result = produce_package(
        resumed,
        resume_client,
        request_id="request-next",
        run_id="run-next",
        package_id="package-next",
        created_at="2026-07-10T00:01:00Z",
        destination=tmp_path / "package-next",
    )
    assert resume_client.calls == ["video_003", "video_004"]
    claims = resumed_result.verification.verified_claims
    assert claims is not None
    assert claims.collection_progress == CollectionProgress(CollectionProgressState.EXHAUSTED)
    assert claims.resumes_run_id == "run"
    assert claims.prior_run_ids == ("run",)
    dispositions = {item.item_id: item.outcome for item in claims.item_dispositions}
    assert dispositions["youtube-video-video_001"] == "unchanged"
    assert "youtube-video-video_002" not in dispositions
    next_path = tmp_path / "checkpoint-next.json"
    next_json = json.loads(next_path.read_bytes())
    assert [item["video_id"] for item in next_json["completed"]] == [
        "video_001",
        "video_003",
        "video_004",
    ]
    assert next_json["pending_video_ids"] == []
    completed = next_json["completed"][0]
    assert completed["captured_path"] is None
    assert (tmp_path / completed["normalized_path"]).read_bytes() == (
        b"Hello from the creator.\n\n**Ada:** Welcome aboard.\n"
    )


def test_raw_retention_opt_in_applies_to_package_and_checkpoint(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    result = produce_package(
        YouTubeOptions(
            PLAYLIST,
            ScopeKind.COLLECTION,
            1,
            retain_raw_captions=True,
            checkpoint_output=checkpoint_path,
        ),
        single_client(creator_track()),
        request_id="request",
        run_id="run",
        package_id="package",
        created_at="2026-07-10T00:00:00Z",
        destination=tmp_path / "package",
    )
    assert result.verification.verified_claims is not None
    checkpoint = json.loads(checkpoint_path.read_bytes())
    assert checkpoint["retain_raw_captions"] is True
    completed = checkpoint["completed"][0]
    assert (tmp_path / completed["captured_path"]).read_bytes() == creator_track().data
    assert (tmp_path / "package/artifacts/youtube-video-video_001/captured.vtt").is_file()


def test_legacy_raw_checkpoint_and_retention_mode_change_fail_closed(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    opts = YouTubeOptions(
        PLAYLIST,
        ScopeKind.COLLECTION,
        1,
        checkpoint_output=checkpoint_path,
    )
    produce_package(
        opts,
        single_client(creator_track()),
        request_id="request",
        run_id="run",
        package_id="package",
        created_at="2026-07-10T00:00:00Z",
        destination=tmp_path / "package",
    )
    fingerprint = request_fingerprint(opts.acquisition_request("ignored", tmp_path).as_dict())
    current = json.loads(checkpoint_path.read_bytes())
    current["schema_version"] = "1.2.0"
    current["completed"][0]["captured_path"] = "checkpoint.data/video/captured.vtt"
    checkpoint_path.write_text(json.dumps(current))
    with pytest.raises(ValueError, match="unsupported checkpoint schema"):
        load_checkpoint(checkpoint_path, expected_fingerprint=fingerprint)

    current["schema_version"] = "1.3.0"
    current["completed"][0]["captured_path"] = None
    checkpoint_path.write_text(json.dumps(current))
    with pytest.raises(ValueError, match="raw-caption retention mismatch"):
        load_checkpoint(
            checkpoint_path,
            expected_fingerprint=current["request_fingerprint"],
            expected_retain_raw_captions=True,
        )


def test_fully_processed_bounded_collection_claims_exhausted(tmp_path: Path) -> None:
    discovery = Discovery(
        PLAYLIST,
        PLAYLIST,
        "playlist_001",
        (PlaylistEntry("video_001", 1), PlaylistEntry("video_002", 2)),
        True,
    )
    result = produce_package(
        YouTubeOptions(PLAYLIST, ScopeKind.COLLECTION, 2),
        FakeClient(
            discovery,
            {
                "video_001": video("video_001", creator_track()),
                "video_002": video("video_002", creator_track()),
            },
        ),
        request_id="request-exhausted",
        run_id="run-exhausted",
        package_id="package-exhausted",
        created_at="2026-07-10T00:00:00Z",
        destination=tmp_path / "package",
    )
    claims = result.verification.verified_claims
    assert claims is not None
    assert claims.collection_progress == CollectionProgress(CollectionProgressState.EXHAUSTED)
    assert len(claims.item_dispositions) == 2


def test_verification_summary_excludes_provider_extensions_and_content(tmp_path: Path) -> None:
    result = produce_package(
        options(),
        single_client(creator_track()),
        request_id="request-summary",
        run_id="run-summary",
        package_id="package-summary",
        created_at="2026-07-10T00:00:00Z",
        destination=tmp_path / "package",
    )
    serialized = json.dumps(asdict(result.verification), default=str, sort_keys=True)
    assert "org.ctrl-alt-keith.youtube" not in serialized
    assert "selection_reason" not in serialized
    assert "Hello from the creator" not in serialized
    claims = result.verification.verified_claims
    assert claims is not None
    assert claims.item_dispositions[0].provider == "youtube"


def test_failure_resume_success_preserves_cumulative_attempt_count(tmp_path: Path) -> None:
    discovery = Discovery(
        PLAYLIST,
        PLAYLIST,
        "playlist_001",
        (PlaylistEntry("video_001", 1), PlaylistEntry("video_002", 2)),
        True,
    )
    first_checkpoint = tmp_path / "first.json"
    first_options = YouTubeOptions(
        PLAYLIST,
        ScopeKind.COLLECTION,
        2,
        batch_size=1,
        checkpoint_output=first_checkpoint,
    )
    produce_package(
        first_options,
        FakeClient(
            discovery,
            {
                "video_001": ProviderFailure(
                    ProviderFailureCategory.REMOVED, "fixture-removed"
                )
            },
        ),
        request_id="request-first",
        run_id="run-first",
        package_id="package-first",
        created_at="2026-07-10T00:00:00Z",
        destination=tmp_path / "package-first",
    )
    assert json.loads(first_checkpoint.read_bytes())["attempts"]["video_001"] == 1

    next_checkpoint = tmp_path / "next.json"
    resumed = replace(
        first_options,
        checkpoint_input=first_checkpoint,
        checkpoint_output=next_checkpoint,
    )
    result = produce_package(
        resumed,
        FakeClient(discovery, {"video_001": video("video_001", creator_track())}),
        request_id="request-next",
        run_id="run-next",
        package_id="package-next",
        created_at="2026-07-10T00:01:00Z",
        destination=tmp_path / "package-next",
    )
    claims = result.verification.verified_claims
    assert claims is not None and claims.resumes_run_id == "run-first"
    manifest = json.loads((result.package_path / "package.json").read_bytes())
    assert manifest["final_attempt_counts"]["video_001"] == 2
    assert json.loads(next_checkpoint.read_bytes())["attempts"]["video_001"] == 2


def test_non_actionable_provider_continuation_is_explicitly_blocked(tmp_path: Path) -> None:
    discovery = Discovery(
        PLAYLIST,
        PLAYLIST,
        "playlist_001",
        (PlaylistEntry("video_001", 1),),
        False,
        "opaque-continuation",
    )
    with pytest.raises(CollectionProgressBlocked, match="not actionable"):
        produce_package(
            YouTubeOptions(PLAYLIST, ScopeKind.COLLECTION, 1),
            FakeClient(discovery, {"video_001": video("video_001", creator_track())}),
            request_id="request",
            run_id="run",
            package_id="package",
            created_at="2026-07-10T00:00:00Z",
            destination=tmp_path / "package",
        )
    assert not (tmp_path / "package").exists()


def test_checkpoint_validation_and_changed_playlist_reconciliation(tmp_path: Path) -> None:
    fingerprint = request_fingerprint({"request": "fixture"})
    path = tmp_path / "checkpoint.json"
    captured = b"captured fixture"
    normalized = b"normalized fixture\n"
    captured_path, normalized_path = save_checkpoint_artifacts(
        path,
        video_id="video_001",
        captured=captured,
        normalized=normalized,
    )
    checkpoint = YouTubeCheckpoint(
        fingerprint,
        "0.1.0",
        "1.0.0",
        "playlist_001",
        ("video_001", "video_002"),
        (
            CompletedCheckpointItem(
                "video_001",
                hashlib.sha256(captured).hexdigest(),
                hashlib.sha256(normalized).hexdigest(),
                "completed",
                1,
                captured_path,
                normalized_path,
                "https://www.youtube.com/watch?v=video_001",
                "Fixture title",
                "Fixture channel",
                "20260710",
                "en",
                "creator",
                "vtt",
                None,
                "playlist_001",
                1,
            ),
        ),
        {"video_001": "completed"},
        {"video_001": 1},
        ("video_002",),
        None,
        "item:video_001",
        "run-fixture",
        "package-fixture",
        True,
    )
    save_checkpoint(checkpoint, path)
    loaded = load_checkpoint(path, expected_fingerprint=fingerprint)
    assert reconcile_video_ids(loaded, ("video_003", "video_001")) == (
        ("video_001",),
        ("video_003",),
    )
    normalized_file = tmp_path / normalized_path
    normalized_file.write_bytes(b"modified\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_checkpoint(path, expected_fingerprint=fingerprint)
    normalized_file.write_bytes(normalized)
    with pytest.raises(ValueError, match="fingerprint"):
        load_checkpoint(path, expected_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="adapter version"):
        load_checkpoint(
            path,
            expected_fingerprint=fingerprint,
            expected_adapter_version="different",
        )
    corrupt = checkpoint.as_dict()
    corrupt["pending_video_ids"] = ["video_unknown"]
    path.write_text(json.dumps(corrupt))
    with pytest.raises(ValueError, match="corrupt"):
        load_checkpoint(path, expected_fingerprint=fingerprint)
    corrupt = checkpoint.as_dict()
    completed = corrupt["completed"]
    assert isinstance(completed, list) and isinstance(completed[0], dict)
    completed[0]["normalized_sha256"] = "not-a-digest"
    path.write_text(json.dumps(corrupt))
    with pytest.raises(ValueError, match="corrupt"):
        load_checkpoint(path, expected_fingerprint=fingerprint)
    path.write_text("not-json")
    with pytest.raises(ValueError, match="corrupt"):
        load_checkpoint(path, expected_fingerprint=fingerprint)


def test_checkpoint_read_and_depth_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    path.write_bytes(b"{" + b"x" * MAX_CHECKPOINT_BYTES + b"}")
    with pytest.raises(ValueError, match="byte limit"):
        load_checkpoint(path, expected_fingerprint="0" * 64)
    nested: object = "leaf"
    for _ in range(10):
        nested = {"nested": nested}
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.3.0",
                "request_fingerprint": "0" * 64,
                "bounded_discovery": nested,
            }
        )
    )
    with pytest.raises(ValueError, match="depth limit"):
        load_checkpoint(path, expected_fingerprint="0" * 64)


def test_yt_dlp_exception_translation_uses_structured_evidence() -> None:
    timeout = YtDlpClient._translate_exception(TimeoutError())
    assert timeout.category is ProviderFailureCategory.TIMEOUT and timeout.retryable

    class StructuredHttpError(RuntimeError):
        status = 429

    throttled = YtDlpClient._translate_exception(StructuredHttpError())
    assert throttled.category is ProviderFailureCategory.THROTTLED and throttled.retryable
    unknown = YtDlpClient._translate_exception(RuntimeError("private words ignored"))
    assert unknown.category is ProviderFailureCategory.UNAVAILABLE


class StubYtDlp:
    def __init__(self, info: dict[str, object], response: bytes = b"") -> None:
        self.info = info
        self.response = response
        self.opened_urls: list[str] = []

    def __enter__(self) -> StubYtDlp:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def extract_info(self, locator: str, *, download: bool) -> dict[str, object]:
        del locator, download
        return self.info

    def urlopen(self, url: str) -> io.BytesIO:
        self.opened_urls.append(url)
        return io.BytesIO(self.response)


def stub_real_client(stub: StubYtDlp) -> YtDlpClient:
    client = object.__new__(YtDlpClient)
    cast(Any, client)._module = SimpleNamespace(YoutubeDL=lambda params: stub)
    cast(Any, client)._version = "fixture-real-boundary"
    return client


def test_real_client_rejects_excess_candidates_before_acquisition() -> None:
    candidates = [
        {"ext": "vtt", "url": f"https://captions.test/{index}?signature=secret"}
        for index in range(3)
    ]
    stub = StubYtDlp({"subtitles": {"en": candidates}})
    client = stub_real_client(stub)
    with pytest.raises(ProviderFailure, match="caption-candidate-limit"):
        client.enrich("video_001", options(max_caption_candidates=2))
    assert stub.opened_urls == []


def test_real_client_caption_read_is_bounded() -> None:
    signed = "https://captions.test/track?signature=secret"
    stub = StubYtDlp(
        {"subtitles": {"en": [{"ext": "vtt", "url": signed}]}},
        b"x" * 9,
    )
    client = stub_real_client(stub)
    with pytest.raises(ProviderFailure, match="caption-size-limit"):
        client.enrich("video_001", options(max_caption_bytes=8))
    assert stub.opened_urls == [signed]


def test_real_client_preserves_unsupported_format_evidence_without_url() -> None:
    signed = "https://captions.test/track?signature=secret"
    stub = StubYtDlp({"subtitles": {"en": [{"ext": "ttml", "url": signed}]}})
    observation = stub_real_client(stub).enrich("video_001", options())
    assert observation.captions[0].format == "ttml"
    assert observation.caption_candidates[0].format == "ttml"
    assert stub.opened_urls == []
    assert "signature" not in repr(observation)


def test_real_client_rejects_discovery_beyond_requested_bound() -> None:
    stub = StubYtDlp(
        {
            "id": "playlist_001",
            "entries": [{"id": "video_001"}, {"id": "video_002"}],
        }
    )
    client = stub_real_client(stub)
    with pytest.raises(ProviderFailure, match="provider-shape:playlist-entries"):
        client.discover(YouTubeOptions(PLAYLIST, ScopeKind.COLLECTION, 1))


def test_deterministic_replay_produces_identical_package_bytes(tmp_path: Path) -> None:
    package = produce(tmp_path, single_client(creator_track()))
    first = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
    }
    content_address = hashlib.sha256(first["package.json"]).hexdigest()
    shutil.rmtree(package)
    package = produce(tmp_path, single_client(creator_track()))
    second = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
    }
    assert first == second
    assert second["package.sha256"] == f"{content_address}\n".encode()


def test_fake_client_suite_never_uses_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network"))
    produce(tmp_path, single_client(creator_track()))
