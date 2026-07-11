"""Narrow optional yt-dlp boundary.

The Python API receives explicit options and does not invoke yt-dlp's CLI config
loader. ``ignoreconfig`` is also set defensively. No media or ffmpeg operation
is requested; caption URLs are used transiently and never returned.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol, cast

from .config import YouTubeOptions, parse_locator
from .models import (
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

    def enrich(self, video_id: str) -> VideoObservation: ...


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
        entries: list[PlaylistEntry] = []
        for index, raw in enumerate(info.get("entries") or (), 1):
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                continue
            position = raw.get("playlist_index")
            availability = raw.get("availability")
            failure = None
            if availability == "private":
                failure = ProviderFailureCategory.PRIVATE
            elif availability in {"needs_auth", "premium", "subscriber_only"}:
                failure = ProviderFailureCategory.UNAVAILABLE
            entries.append(
                PlaylistEntry(
                    raw["id"],
                    position if isinstance(position, int) else index,
                    failure is None,
                    failure,
                )
            )
        playlist_id = str(info.get("id") or resource_id)
        return Discovery(
            options.locator,
            str(info.get("webpage_url") or f"https://www.youtube.com/playlist?list={playlist_id}"),
            playlist_id,
            tuple(entries[: options.max_items]),
            True,
        )

    def enrich(self, video_id: str) -> VideoObservation:
        locator = f"https://www.youtube.com/watch?v={video_id}"
        try:
            with self._youtube_dl(noplaylist=True) as ydl:
                info = cast(dict[str, Any], ydl.extract_info(locator, download=False))
                tracks: list[CaptionTrack] = []
                for field, kind in (
                    ("subtitles", CaptionKind.CREATOR),
                    ("automatic_captions", CaptionKind.AUTOMATIC),
                ):
                    collection = info.get(field) or {}
                    if not isinstance(collection, dict):
                        continue
                    for language, candidates in collection.items():
                        if not isinstance(language, str) or not isinstance(candidates, list):
                            continue
                        vtt = next(
                            (
                                item
                                for item in candidates
                                if isinstance(item, dict)
                                and item.get("ext") == "vtt"
                                and isinstance(item.get("url"), str)
                            ),
                            None,
                        )
                        if vtt is None:
                            continue
                        # The signed URL is consumed inside the boundary and discarded.
                        with ydl.urlopen(vtt["url"]) as response:
                            data = response.read()
                        name = vtt.get("name")
                        tracks.append(
                            CaptionTrack(
                                language,
                                kind,
                                "vtt",
                                data,
                                name if isinstance(name, str) else None,
                            )
                        )
        except Exception as exc:
            raise self._translate_exception(exc) from exc
        return VideoObservation(
            video_id,
            str(info.get("webpage_url") or locator),
            info.get("title") if isinstance(info.get("title"), str) else None,
            info.get("channel") if isinstance(info.get("channel"), str) else None,
            info.get("upload_date") if isinstance(info.get("upload_date"), str) else None,
            tuple(tracks),
        )
