from __future__ import annotations


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def assert_contains_normalized(output: str, expected: str) -> None:
    assert _normalize_whitespace(expected) in _normalize_whitespace(output)
