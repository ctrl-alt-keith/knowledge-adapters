"""Backward-compatible imports for Confluence manifest helpers."""

from knowledge_adapters.manifest import (
    build_manifest_entry,
    manifest_path,
    write_manifest,
    write_manifest_with_context,
)

__all__ = [
    "build_manifest_entry",
    "manifest_path",
    "write_manifest",
    "write_manifest_with_context",
]
