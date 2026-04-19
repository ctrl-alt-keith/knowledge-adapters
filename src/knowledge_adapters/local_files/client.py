"""File-reading layer for the local files adapter."""

from __future__ import annotations

from pathlib import Path


def fetch_file(file_path: str) -> dict[str, object]:
    """Read a local file into the shared normalized payload shape."""
    path = Path(file_path).expanduser().resolve()
    content = path.read_text(encoding="utf-8")

    return {
        "title": path.name,
        "canonical_id": str(path),
        "source_url": path.as_uri(),
        "content": content,
        "source": "local_files",
        "adapter": "local_files",
    }
