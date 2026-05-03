"""Shared failure classification helpers for adapter errors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class AdapterFailureClass(StrEnum):
    """Stable adapter failure classes for operator handling and tests."""

    EXPECTED_RETRYABLE = "expected_retryable"
    PERMANENT = "permanent"
    AUTH = "auth"
    CONFIGURATION = "configuration"
    PROVIDER = "provider"


@dataclass(frozen=True)
class AdapterFailureClassification:
    """Structured classification for one adapter failure."""

    failure_class: AdapterFailureClass
    provider_status_code: int | None = None
    retry_after: str | None = None


class ClassifiedAdapterError(Protocol):
    """Protocol for exceptions that carry adapter failure classification."""

    classification: AdapterFailureClassification | None


def response_or_config_failure(exc: Exception) -> AdapterFailureClassification:
    """Classify untyped adapter exceptions without changing their public type."""
    if isinstance(exc, ValueError) and str(exc).startswith("Response error:"):
        return AdapterFailureClassification(AdapterFailureClass.PERMANENT)
    return AdapterFailureClassification(AdapterFailureClass.CONFIGURATION)


def adapter_failure_classification(exc: Exception) -> AdapterFailureClassification | None:
    """Return structured classification attached to an adapter exception."""
    classification = getattr(exc, "classification", None)
    if isinstance(classification, AdapterFailureClassification):
        return classification
    return None


def adapter_failure_lines(
    exc: Exception,
    *,
    fallback: AdapterFailureClassification | None = None,
) -> tuple[str, ...]:
    """Render stable CLI detail lines for an adapter failure."""
    classification = adapter_failure_classification(exc) or fallback
    if classification is None:
        return ()

    lines = [f"failure_class: {classification.failure_class.value}"]
    if classification.provider_status_code is not None:
        lines.append(f"provider_status_code: {classification.provider_status_code}")
    if classification.retry_after is not None:
        lines.append(f"retry_after: {classification.retry_after}")
    return tuple(lines)
