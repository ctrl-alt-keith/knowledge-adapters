"""Deterministic WebVTT-to-Markdown normalization."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

NORMALIZER_NAME = "youtube-webvtt-to-markdown"
NORMALIZER_VERSION = "1.0.0"
TRANSFORMS = (
    "utf8-strict",
    "line-endings-lf",
    "unicode-nfc",
    "webvtt-transport-headers-removed",
    "timestamps-omitted",
    "speaker-labels-markdown-bold",
    "rolling-cues-collapsed",
    "one-trailing-newline",
)
TIMING_RE = re.compile(
    r"^(?:\d{2}:)?\d{2}:\d{2}\.\d{3}\s+-->\s+(?:\d{2}:)?\d{2}:\d{2}\.\d{3}(?:\s+.*)?$"
)
VOICE_RE = re.compile(r"<v(?:\.[^ >]+)*\s+([^>]+)>(.*?)</v>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


class CaptionNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedCaption:
    data: bytes
    transforms: tuple[str, ...] = TRANSFORMS


def _clean_text(lines: list[str]) -> str:
    value = " ".join(line.strip() for line in lines if line.strip())
    value = VOICE_RE.sub(lambda match: f"**{match.group(1).strip()}:** {match.group(2)}", value)
    value = TAG_RE.sub("", value)
    return " ".join(html.unescape(value).split())


def normalize_webvtt(data: bytes, *, automatic: bool) -> NormalizedCaption:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CaptionNormalizationError("captions are not valid UTF-8") from exc
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = text.split("\n")
    if not lines or lines[0].strip() != "WEBVTT":
        raise CaptionNormalizationError("missing WEBVTT header")
    cues: list[str] = []
    index = 1
    # WebVTT permits transport metadata between the header and first blank line.
    while index < len(lines) and lines[index].strip():
        index += 1
    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break
        if lines[index].startswith(("NOTE", "STYLE", "REGION")):
            while index < len(lines) and lines[index].strip():
                index += 1
            continue
        if not TIMING_RE.fullmatch(lines[index].strip()):
            index += 1
            if index >= len(lines) or not TIMING_RE.fullmatch(lines[index].strip()):
                raise CaptionNormalizationError("malformed WebVTT cue")
        index += 1
        if (
            automatic
            and index + 1 < len(lines)
            and not lines[index].strip()
            and lines[index + 1].strip()
            and not TIMING_RE.fullmatch(lines[index + 1].strip())
        ):
            index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index])
            index += 1
        cleaned = _clean_text(body)
        if not cleaned:
            continue
        if automatic and cues and cleaned.startswith(cues[-1]):
            cues[-1] = cleaned
        elif not cues or cleaned != cues[-1]:
            cues.append(cleaned)
    if not cues:
        raise CaptionNormalizationError("WebVTT contains no spoken cues")
    return NormalizedCaption(("\n\n".join(cues) + "\n").encode())
