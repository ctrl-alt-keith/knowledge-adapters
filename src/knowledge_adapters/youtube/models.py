"""Adapter-local YouTube observations and failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CaptionKind(StrEnum):
    CREATOR = "creator"
    AUTOMATIC = "automatic"


class ProviderFailureCategory(StrEnum):
    PRIVATE = "private"
    REMOVED = "removed"
    AGE_RESTRICTED = "age-restricted"
    GEO_RESTRICTED = "geo-restricted"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    THROTTLED = "throttled"
    TRANSIENT = "transient"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CaptionTrack:
    language: str
    kind: CaptionKind
    format: str
    data: bytes
    name: str | None = None


@dataclass(frozen=True)
class CaptionCandidate:
    language: str
    kind: CaptionKind
    format: str
    name: str | None = None


@dataclass(frozen=True)
class PlaylistEntry:
    video_id: str
    position: int | None
    available: bool = True
    failure: ProviderFailureCategory | None = None


@dataclass(frozen=True)
class Discovery:
    requested_locator: str
    resolved_locator: str
    playlist_id: str | None
    entries: tuple[PlaylistEntry, ...]
    exhausted: bool
    continuation: str | None = None


@dataclass(frozen=True)
class VideoObservation:
    video_id: str
    resolved_locator: str
    title: str | None
    channel: str | None
    published_at: str | None
    captions: tuple[CaptionTrack, ...]
    caption_candidates: tuple[CaptionCandidate, ...] = ()


class ProviderFailure(RuntimeError):
    """Structured provider failure; message text never determines category."""

    def __init__(
        self,
        category: ProviderFailureCategory,
        code: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.category = category
        self.code = code
        self.retryable = retryable
