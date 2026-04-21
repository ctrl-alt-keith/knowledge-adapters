"""File-reading layer for the local files adapter."""

from __future__ import annotations

from pathlib import Path


def fetch_file(file_path: str) -> dict[str, object]:
    """Read a local file into the shared normalized payload shape."""
    input_path = Path(file_path).expanduser()
    if not input_path.exists():
        raise ValueError(f"File does not exist: {input_path}. Check --file-path and try again.")
    if not input_path.is_file():
        raise ValueError(
            f"Path is not a regular file: {input_path}. Supply a single UTF-8 text file."
        )

    path = input_path.resolve()
    try:
        content = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ValueError(
            f"File is not readable: {path}. Check the file permissions."
        ) from exc
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"File is not readable as UTF-8 text: {path}. Supply a UTF-8 text file."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Could not read file: {path}. Check --file-path and try again.") from exc

    return {
        "title": path.name,
        "canonical_id": str(path),
        "source_url": path.as_uri(),
        "content": content,
        "source": "local_files",
        "adapter": "local_files",
    }
