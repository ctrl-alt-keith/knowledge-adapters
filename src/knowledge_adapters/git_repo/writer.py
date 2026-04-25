"""File writing utilities for the git_repo adapter."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def markdown_path(output_dir: str, repo_path: str) -> Path:
    """Return the deterministic markdown path for one repository file."""
    repo_relative_path = PurePosixPath(repo_path)
    output_relative_path = repo_relative_path.with_name(f"{repo_relative_path.name}.md")
    return Path(output_dir) / "pages" / Path(*output_relative_path.parts)


def write_markdown(
    output_dir: str,
    repo_path: str,
    markdown: str,
    *,
    dry_run: bool = False,
) -> Path:
    """Write normalized markdown to a deterministic local path."""
    output_path = markdown_path(output_dir, repo_path)
    pages_dir = output_path.parent

    if dry_run:
        return output_path

    pages_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path
