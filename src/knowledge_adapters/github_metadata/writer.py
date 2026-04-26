"""File writing utilities for the github_metadata adapter."""

from __future__ import annotations

from pathlib import Path

_RESOURCE_DIRECTORIES = {
    "issue": "issues",
    "pull_request": "pull_requests",
    "release": "releases",
}


def markdown_path(output_dir: str, resource_type: str, identifier: int | str) -> Path:
    """Return the deterministic markdown path for one GitHub metadata record."""
    try:
        directory = _RESOURCE_DIRECTORIES[resource_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported github_metadata resource_type: {resource_type!r}.") from exc
    return Path(output_dir) / directory / f"{identifier}.md"


def write_markdown(
    output_dir: str,
    resource_type: str,
    identifier: int | str,
    markdown: str,
    *,
    dry_run: bool = False,
) -> Path:
    """Write normalized GitHub metadata markdown to a deterministic local path."""
    output_path = markdown_path(output_dir, resource_type, identifier)

    if dry_run:
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path
