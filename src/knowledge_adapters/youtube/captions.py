"""Deterministic caption-track selection."""

from __future__ import annotations

from dataclasses import dataclass

from .config import BaseLanguageFallback, CaptionPolicy, YouTubeOptions
from .models import CaptionKind, CaptionTrack


@dataclass(frozen=True)
class CaptionSelection:
    track: CaptionTrack
    reason: str
    candidates: tuple[dict[str, str], ...]


def _language_rank(track: CaptionTrack, options: YouTubeOptions) -> int | None:
    for index, preferred in enumerate(options.languages):
        if track.language.lower() == preferred.lower():
            return index * 2
        if options.base_language_fallback is BaseLanguageFallback.ENABLED:
            if track.language.split("-", 1)[0].lower() == preferred.split("-", 1)[0].lower():
                return index * 2 + 1
    return None


def select_caption(
    tracks: tuple[CaptionTrack, ...], options: YouTubeOptions
) -> CaptionSelection | None:
    eligible: list[tuple[CaptionTrack, int]] = []
    for track in tracks:
        rank = _language_rank(track, options)
        if rank is not None:
            eligible.append((track, rank))
    if options.caption_policy is CaptionPolicy.CREATOR_ONLY:
        eligible = [(track, rank) for track, rank in eligible if track.kind is CaptionKind.CREATOR]

    def key(value: tuple[CaptionTrack, int]) -> tuple[int, int, int, str, str]:
        track, rank = value
        kind_rank = 0 if track.kind is CaptionKind.CREATOR else 1
        format_rank = 0 if track.format.lower() == "vtt" else 1
        if options.caption_policy is CaptionPolicy.CREATOR_THEN_AUTOMATIC:
            return kind_rank, rank, format_rank, track.language, track.name or ""
        return rank, kind_rank, format_rank, track.language, track.name or ""

    candidates = tuple(
        {
            "language": track.language,
            "kind": track.kind.value,
            "format": track.format,
            **({"name": track.name} if track.name else {}),
        }
        for track in sorted(
            tracks, key=lambda item: (item.language, item.kind.value, item.name or "")
        )
    )
    if not eligible:
        return None
    selected, rank = min(eligible, key=key)
    match = "exact" if rank % 2 == 0 else "base-language-fallback"
    reason = f"{options.caption_policy.value}:{match}:{selected.language}:{selected.kind.value}"
    return CaptionSelection(selected, reason, candidates)
