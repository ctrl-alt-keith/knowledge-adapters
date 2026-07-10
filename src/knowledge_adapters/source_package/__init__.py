"""Provider-neutral Source Package construction and verification."""

from .core import (
    PackageBuilder,
    SealResult,
    VerificationIssue,
    VerificationResult,
    canonical_json_bytes,
    verify_package,
)
from .models import (
    AdapterIdentity,
    Artifact,
    ArtifactInventoryEntry,
    ItemOutcome,
    PackageItem,
)

__all__ = [
    "AdapterIdentity",
    "Artifact",
    "ArtifactInventoryEntry",
    "ItemOutcome",
    "PackageBuilder",
    "PackageItem",
    "SealResult",
    "VerificationIssue",
    "VerificationResult",
    "canonical_json_bytes",
    "verify_package",
]
