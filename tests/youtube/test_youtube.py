from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from knowledge_adapters.source_package import verify_package
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
    CompletedCheckpointItem,
    YouTubeCheckpoint,
    load_checkpoint,
    reconcile_video_ids,
    request_fingerprint,
    save_checkpoint,
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
        videos: dict[str, VideoObservation | list[VideoObservation | ProviderFailure]],
    ) -> None:
        self.discovery = discovery
        self.videos = videos
        self.calls: list[str] = []

    def discover(self, options: YouTubeOptions) -> Discovery:
        del options
        return self.discovery

    def enrich(self, video_id: str) -> VideoObservation:
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
    )
    assert result.verification.ok
    return destination


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"max_items": 0}, "positive"),
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
    assert result.verified_claims.adapter.revision == "yt-dlp/fixture-2026.07"
    files = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()}
    assert not any(path.endswith("captured.vtt") for path in files)
    all_bytes = b"".join(path.read_bytes() for path in package.rglob("*") if path.is_file())
    assert b"signature=" not in all_bytes and b"secret" not in all_bytes


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


def test_partial_batch_writes_checkpoint_but_does_not_seal(tmp_path: Path) -> None:
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
    with pytest.raises(CollectionProgressBlocked, match="canonical collection progress"):
        produce_package(
            opts,
            FakeClient(discovery, dict(partial_videos)),
            request_id="request",
            run_id="run",
            package_id="package",
            created_at="2026-07-10T00:00:00Z",
            destination=tmp_path / "package",
        )
    assert checkpoint_path.is_file() and not (tmp_path / "package").exists()
    checkpoint_json = json.loads(checkpoint_path.read_bytes())
    assert [item["video_id"] for item in checkpoint_json["completed"]] == [
        "video_001",
        "video_002",
    ]
    assert checkpoint_json["pending_video_ids"] == ["video_003"]
    assert all(len(item["normalized_sha256"]) == 64 for item in checkpoint_json["completed"])
    resumed = replace(
        opts,
        checkpoint_input=checkpoint_path,
        checkpoint_output=tmp_path / "checkpoint-next.json",
    )
    with pytest.raises(CollectionProgressBlocked, match="resume lineage"):
        produce_package(
            resumed,
            FakeClient(discovery, dict(partial_videos)),
            request_id="request-next",
            run_id="run-next",
            package_id="package-next",
            created_at="2026-07-10T00:01:00Z",
            destination=tmp_path / "package-next",
        )


def test_checkpoint_validation_and_changed_playlist_reconciliation(tmp_path: Path) -> None:
    fingerprint = request_fingerprint({"request": "fixture"})
    checkpoint = YouTubeCheckpoint(
        fingerprint,
        "0.1.0",
        "1.0.0",
        "playlist_001",
        ("video_001", "video_002"),
        (CompletedCheckpointItem("video_001", "a" * 64, "b" * 64, "completed", 1),),
        {"video_001": "completed"},
        {"video_001": 1},
        ("video_002",),
        None,
        "item:video_001",
    )
    path = tmp_path / "checkpoint.json"
    save_checkpoint(checkpoint, path)
    loaded = load_checkpoint(path, expected_fingerprint=fingerprint)
    assert reconcile_video_ids(loaded, ("video_003", "video_001")) == (
        ("video_001",),
        ("video_003",),
    )
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


def test_yt_dlp_exception_translation_uses_structured_evidence() -> None:
    timeout = YtDlpClient._translate_exception(TimeoutError())
    assert timeout.category is ProviderFailureCategory.TIMEOUT and timeout.retryable

    class StructuredHttpError(RuntimeError):
        status = 429

    throttled = YtDlpClient._translate_exception(StructuredHttpError())
    assert throttled.category is ProviderFailureCategory.THROTTLED and throttled.retryable
    unknown = YtDlpClient._translate_exception(RuntimeError("private words ignored"))
    assert unknown.category is ProviderFailureCategory.UNAVAILABLE


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
