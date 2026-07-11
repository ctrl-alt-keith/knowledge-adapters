"""Typed, bounded YouTube acquisition configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from knowledge_adapters.source_package import AcquisitionRequest

YOUTUBE_EXTENSION = "org.ctrl-alt-keith.youtube"
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,64}\Z")
PLAYLIST_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,128}\Z")
SECRET_QUERY_KEYS = frozenset({"cookie", "cookies", "token", "key", "password", "auth"})


class ScopeKind(StrEnum):
    RESOURCE = "resource"
    COLLECTION = "collection"


class CaptionPolicy(StrEnum):
    CREATOR_ONLY = "creator-only"
    CREATOR_THEN_AUTOMATIC = "creator-then-automatic"
    AUTOMATIC_ALLOWED = "automatic-allowed"


class NoCaptionOutcome(StrEnum):
    SKIP = "skip"
    FAIL = "fail"


class BaseLanguageFallback(StrEnum):
    DISABLED = "disabled"
    ENABLED = "enabled"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")


@dataclass(frozen=True)
class YouTubeOptions:
    locator: str
    scope: ScopeKind
    max_items: int
    languages: tuple[str, ...] = ("en",)
    base_language_fallback: BaseLanguageFallback = BaseLanguageFallback.DISABLED
    caption_policy: CaptionPolicy = CaptionPolicy.CREATOR_THEN_AUTOMATIC
    no_caption_outcome: NoCaptionOutcome = NoCaptionOutcome.SKIP
    retain_raw_captions: bool = False
    batch_size: int | None = None
    checkpoint_input: Path | None = None
    checkpoint_output: Path | None = None
    retry: RetryPolicy = RetryPolicy()

    def __post_init__(self) -> None:
        kind, _ = parse_locator(self.locator)
        expected = "video" if self.scope is ScopeKind.RESOURCE else "playlist"
        if kind != expected:
            raise ValueError(f"{self.scope.value} scope requires a {expected} locator")
        if self.max_items <= 0:
            raise ValueError("max_items must be positive")
        if self.scope is ScopeKind.RESOURCE and self.max_items != 1:
            raise ValueError("resource scope requires max_items=1")
        if self.batch_size is not None and not 1 <= self.batch_size <= self.max_items:
            raise ValueError("batch_size must be positive and no greater than max_items")
        if not self.languages or any(
            not language or len(language) > 64 for language in self.languages
        ):
            raise ValueError("at least one bounded language preference is required")
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("language preferences must be unique")
        if self.checkpoint_input is not None and self.scope is ScopeKind.RESOURCE:
            raise ValueError("checkpoint input is supported only for collection scope")
        if self.checkpoint_input is not None and self.checkpoint_output is None:
            raise ValueError("checkpoint resume requires an output checkpoint path")
        if self.checkpoint_input is not None and self.checkpoint_input == self.checkpoint_output:
            raise ValueError("checkpoint input and output paths must differ")

    def acquisition_request(self, request_id: str, output: Path) -> AcquisitionRequest:
        kind, resource_id = parse_locator(self.locator)
        selection: dict[str, object] = {
            "languages": list(self.languages),
            "base_language_fallback": self.base_language_fallback.value,
            "caption_policy": self.caption_policy.value,
            "no_caption_outcome": self.no_caption_outcome.value,
            "retain_raw_captions": self.retain_raw_captions,
        }
        if self.batch_size is not None:
            selection["batch_size"] = self.batch_size
        return AcquisitionRequest(
            request_id=request_id,
            adapter_type="video-host",
            targets=(self.locator,),
            scope={"kind": self.scope.value, "max_items": self.max_items},
            output_location=str(output),
            checkpoint_reference=(
                str(self.checkpoint_input) if self.checkpoint_input is not None else None
            ),
            selection=selection,
            retry_policy={"max_attempts": self.retry.max_attempts},
            expected_contract="1.x",
            extensions={YOUTUBE_EXTENSION: {"locator_kind": kind, "resource_id": resource_id}},
        )


def parse_locator(locator: str) -> tuple[str, str]:
    if len(locator) > 2048 or any(char.isspace() for char in locator):
        raise ValueError("unsupported YouTube locator")
    parsed = urlparse(locator)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("YouTube locators must be non-secret HTTPS URLs")
    host = (parsed.hostname or "").lower()
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        raise ValueError("unsupported YouTube host")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if SECRET_QUERY_KEYS & {key.lower() for key in query}:
        raise ValueError("secrets must not be embedded in locators")
    if host == "youtu.be":
        value = parsed.path.strip("/")
        if parsed.query or not VIDEO_ID_RE.fullmatch(value):
            raise ValueError("unsupported short YouTube locator")
        return "video", value
    if parsed.path == "/watch" and set(query) == {"v"} and len(query["v"]) == 1:
        value = query["v"][0]
        if VIDEO_ID_RE.fullmatch(value):
            return "video", value
    if parsed.path == "/playlist" and set(query) == {"list"} and len(query["list"]) == 1:
        value = query["list"][0]
        if PLAYLIST_ID_RE.fullmatch(value):
            return "playlist", value
    raise ValueError("unsupported or ambiguous YouTube locator")
