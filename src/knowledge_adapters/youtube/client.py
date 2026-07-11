"""Narrow optional yt-dlp boundary.

The Python API receives explicit options and does not invoke yt-dlp's CLI config
loader. ``ignoreconfig`` is also set defensively. No media or ffmpeg operation
is requested; caption URLs are used transiently and never returned.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import Any, BinaryIO, Protocol, cast

from .captions import select_caption
from .config import MAX_PROVIDER_TEXT_BYTES, YouTubeOptions, parse_locator
from .models import (
    CaptionCandidate,
    CaptionKind,
    CaptionTrack,
    Discovery,
    PlaylistEntry,
    ProviderFailure,
    ProviderFailureCategory,
    VideoObservation,
)


class YouTubeClient(Protocol):
    @property
    def version(self) -> str: ...

    def discover(self, options: YouTubeOptions) -> Discovery: ...

    def enrich(self, video_id: str, options: YouTubeOptions) -> VideoObservation: ...


class YtDlpClient:
    """Caption-only yt-dlp client; import succeeds only with the youtube extra."""

    def __init__(self) -> None:
        try:
            self._module = import_module("yt_dlp")
            version_module = import_module("yt_dlp.version")
        except ModuleNotFoundError as exc:
            raise RuntimeError("install knowledge-adapters[youtube] to use yt-dlp") from exc
        self._version = str(getattr(version_module, "__version__", "unknown"))

    @property
    def version(self) -> str:
        return self._version

    def _youtube_dl(self, **overrides: object) -> Any:
        params: dict[str, object] = {
            "ignoreconfig": True,
            "remote_components": set(),
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noprogress": True,
            "cachedir": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
        }
        params.update(overrides)
        return self._module.YoutubeDL(params)

    @staticmethod
    def _translate_exception(exc: BaseException) -> ProviderFailure:
        if isinstance(exc, ProviderFailure):
            return exc
        current: BaseException | None = exc
        while current is not None:
            if isinstance(current, TimeoutError):
                return ProviderFailure(
                    ProviderFailureCategory.TIMEOUT, "yt-dlp:timeout", retryable=True
                )
            status = getattr(current, "status", None)
            if status == 429:
                return ProviderFailure(
                    ProviderFailureCategory.THROTTLED,
                    "yt-dlp:http-429",
                    retryable=True,
                )
            if isinstance(status, int) and 500 <= status < 600:
                return ProviderFailure(
                    ProviderFailureCategory.TRANSIENT,
                    f"yt-dlp:http-{status}",
                    retryable=True,
                )
            current = current.__cause__
        return ProviderFailure(
            ProviderFailureCategory.UNAVAILABLE,
            f"yt-dlp:{type(exc).__name__}",
            retryable=False,
        )

    @staticmethod
    def _bounded_text(value: object, *, field: str, required: bool = False) -> str | None:
        if value is None and not required:
            return None
        if (
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > MAX_PROVIDER_TEXT_BYTES
        ):
            raise ProviderFailure(
                ProviderFailureCategory.UNAVAILABLE,
                f"provider-shape:{field}",
            )
        return value

    @staticmethod
    def _read_bounded(response: BinaryIO, limit: int) -> bytes:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ProviderFailure(
                ProviderFailureCategory.UNAVAILABLE,
                "caption-size-limit",
            )
        return data

    @staticmethod
    def _language_relevant(language: str, options: YouTubeOptions) -> bool:
        observed = language.lower()
        for preferred in options.languages:
            wanted = preferred.lower()
            if observed == wanted:
                return True
            if (
                options.base_language_fallback.value == "enabled"
                and observed.split("-", 1)[0] == wanted.split("-", 1)[0]
            ):
                return True
        return False

    def discover(self, options: YouTubeOptions) -> Discovery:
        kind, resource_id = parse_locator(options.locator)
        if kind == "video":
            return Discovery(
                options.locator,
                f"https://www.youtube.com/watch?v={resource_id}",
                None,
                (PlaylistEntry(resource_id, 1),),
                True,
            )
        try:
            with self._youtube_dl(extract_flat=True, playlistend=options.max_items) as ydl:
                info = cast(dict[str, Any], ydl.extract_info(options.locator, download=False))
        except Exception as exc:
            raise self._translate_exception(exc) from exc
        if not isinstance(info, dict):
            raise ProviderFailure(ProviderFailureCategory.UNAVAILABLE, "provider-shape:root")
        raw_entries = info.get("entries") or ()
        if (
            not isinstance(raw_entries, Sequence)
            or isinstance(raw_entries, (str, bytes))
            or len(raw_entries) > options.max_items
        ):
            raise ProviderFailure(
                ProviderFailureCategory.UNAVAILABLE, "provider-shape:playlist-entries"
            )
        entries: list[PlaylistEntry] = []
        for index, raw in enumerate(raw_entries, 1):
            if not isinstance(raw, dict):
                raise ProviderFailure(
                    ProviderFailureCategory.UNAVAILABLE, "provider-shape:playlist-entry"
                )
            video_id = self._bounded_text(raw.get("id"), field="video-id", required=True)
            assert video_id is not None
            position = raw.get("playlist_index")
            if position is not None and (not isinstance(position, int) or position <= 0):
                position = None
            availability = raw.get("availability")
            if availability is not None and not isinstance(availability, str):
                raise ProviderFailure(
                    ProviderFailureCategory.UNAVAILABLE, "provider-shape:availability"
                )
            failure = None
            if availability == "private":
                failure = ProviderFailureCategory.PRIVATE
            elif availability in {"needs_auth", "premium", "subscriber_only"}:
                failure = ProviderFailureCategory.UNAVAILABLE
            entries.append(
                PlaylistEntry(
                    video_id,
                    position if isinstance(position, int) else index,
                    failure is None,
                    failure,
                )
            )
        playlist_id = self._bounded_text(
            info.get("id") or resource_id, field="playlist-id", required=True
        )
        assert playlist_id is not None
        resolved = self._bounded_text(info.get("webpage_url"), field="playlist-url")
        return Discovery(
            options.locator,
            resolved or f"https://www.youtube.com/playlist?list={playlist_id}",
            playlist_id,
            tuple(entries[: options.max_items]),
            True,
        )

    def enrich(self, video_id: str, options: YouTubeOptions) -> VideoObservation:
        locator = f"https://www.youtube.com/watch?v={video_id}"
        try:
            with self._youtube_dl(noplaylist=True) as ydl:
                info = cast(dict[str, Any], ydl.extract_info(locator, download=False))
                if not isinstance(info, dict):
                    raise ProviderFailure(
                        ProviderFailureCategory.UNAVAILABLE, "provider-shape:root"
                    )
                candidate_records: list[tuple[CaptionTrack, str | None]] = []
                for field, kind in (
                    ("subtitles", CaptionKind.CREATOR),
                    ("automatic_captions", CaptionKind.AUTOMATIC),
                ):
                    collection = info.get(field) or {}
                    if not isinstance(collection, dict):
                        raise ProviderFailure(
                            ProviderFailureCategory.UNAVAILABLE,
                            f"provider-shape:{field}",
                        )
                    for language, candidates in collection.items():
                        language_value = self._bounded_text(
                            language, field="caption-language", required=True
                        )
                        assert language_value is not None
                        if not self._language_relevant(language_value, options):
                            continue
                        if not isinstance(candidates, list):
                            raise ProviderFailure(
                                ProviderFailureCategory.UNAVAILABLE,
                                "provider-shape:caption-candidates",
                            )
                        for candidate in candidates:
                            if len(candidate_records) >= options.max_caption_candidates:
                                raise ProviderFailure(
                                    ProviderFailureCategory.UNAVAILABLE,
                                    "caption-candidate-limit",
                                )
                            if not isinstance(candidate, dict):
                                raise ProviderFailure(
                                    ProviderFailureCategory.UNAVAILABLE,
                                    "provider-shape:caption-candidate",
                                )
                            caption_format = self._bounded_text(
                                candidate.get("ext") or "unknown",
                                field="caption-format",
                                required=True,
                            )
                            assert caption_format is not None
                            name = self._bounded_text(candidate.get("name"), field="caption-name")
                            url = self._bounded_text(candidate.get("url"), field="caption-url")
                            candidate_records.append(
                                (
                                    CaptionTrack(
                                        language_value, kind, caption_format, b"", name
                                    ),
                                    url,
                                )
                            )
                metadata_tracks = tuple(record[0] for record in candidate_records)
                selected = select_caption(metadata_tracks, options)
                tracks: tuple[CaptionTrack, ...] = ()
                if selected is not None:
                    selected_url = next(
                        url for track, url in candidate_records if track is selected.track
                    )
                    if selected.track.format.lower() != "vtt":
                        tracks = (selected.track,)
                    elif selected_url is None:
                        raise ProviderFailure(
                            ProviderFailureCategory.UNAVAILABLE, "caption-url-missing"
                        )
                    else:
                        # The signed URL is consumed inside the boundary and discarded.
                        with ydl.urlopen(selected_url) as response:
                            data = self._read_bounded(response, options.max_caption_bytes)
                        tracks = (
                            CaptionTrack(
                                selected.track.language,
                                selected.track.kind,
                                selected.track.format,
                                data,
                                selected.track.name,
                            ),
                        )
        except Exception as exc:
            raise self._translate_exception(exc) from exc
        resolved = self._bounded_text(info.get("webpage_url"), field="video-url")
        title = self._bounded_text(info.get("title"), field="title")
        channel = self._bounded_text(info.get("channel"), field="channel")
        published_at = self._bounded_text(info.get("upload_date"), field="upload-date")
        return VideoObservation(
            video_id,
            resolved or locator,
            title,
            channel,
            published_at,
            tracks,
            tuple(
                CaptionCandidate(track.language, track.kind, track.format, track.name)
                for track in metadata_tracks
            ),
        )
