"""Git-backed file ingestion for the git_repo adapter."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class GitRepoFile:
    """One normalized source file loaded from a repository checkout."""

    repo_path: str
    title: str
    canonical_id: str
    source_url: str
    content: str
    source: str = "git_repo"
    adapter: str = "git_repo"


@dataclass(frozen=True)
class SkippedGitRepoFile:
    """One repository file skipped during ingestion."""

    repo_path: str
    reason: str


@dataclass(frozen=True)
class GitRepoSnapshot:
    """Resolved repository checkout plus selected files."""

    repo_dir: Path
    ref: str
    commit_sha: str
    discovered_paths: tuple[str, ...]
    selected_paths: tuple[str, ...]
    files: tuple[GitRepoFile, ...]
    skipped_files: tuple[SkippedGitRepoFile, ...]


def cache_dir_for_repo(repo_url: str) -> Path:
    """Return the deterministic local checkout cache path for one repo URL."""
    repo_hash = hashlib.sha256(repo_url.encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "knowledge-adapters" / "git_repo" / repo_hash


def fetch_repo_snapshot(
    repo_url: str,
    *,
    ref: str | None = None,
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
    subdir: str | None = None,
) -> GitRepoSnapshot:
    """Clone or refresh a repository checkout and read selected UTF-8 files."""
    repo_dir = cache_dir_for_repo(repo_url)
    _ensure_repo_checkout(repo_url, repo_dir)
    resolved_ref = _checkout_ref(repo_dir, ref)
    commit_sha = _run_git(
        "rev-parse",
        "HEAD",
        cwd=repo_dir,
        operation="resolve checked out commit",
    )

    normalized_subdir = normalize_subdir(subdir)
    if normalized_subdir is not None:
        subdir_path = repo_dir / Path(*PurePosixPath(normalized_subdir).parts)
        if not subdir_path.exists():
            raise ValueError(
                f"Subdirectory does not exist at ref {resolved_ref!r}: {normalized_subdir}."
            )
        if not subdir_path.is_dir():
            raise ValueError(
                "Subdirectory path is not a directory at ref "
                f"{resolved_ref!r}: {normalized_subdir}."
            )

    discovered_paths = _list_repo_files(repo_dir, subdir=normalized_subdir)
    selected_paths = tuple(
        repo_path
        for repo_path in discovered_paths
        if _path_is_selected(
            repo_path,
            include_patterns=include,
            exclude_patterns=exclude,
        )
    )

    files: list[GitRepoFile] = []
    skipped_files: list[SkippedGitRepoFile] = []
    for repo_path in selected_paths:
        source_path = repo_dir / Path(*PurePosixPath(repo_path).parts)
        if not source_path.exists():
            skipped_files.append(
                SkippedGitRepoFile(
                    repo_path=repo_path,
                    reason="missing after checkout",
                )
            )
            continue
        if not source_path.is_file():
            skipped_files.append(
                SkippedGitRepoFile(
                    repo_path=repo_path,
                    reason="not a regular file; submodules are not supported",
                )
            )
            continue

        try:
            raw_content = source_path.read_bytes()
        except OSError as exc:
            raise ValueError(f"Could not read repository file: {repo_path}.") from exc

        if b"\x00" in raw_content:
            skipped_files.append(
                SkippedGitRepoFile(
                    repo_path=repo_path,
                    reason="binary file",
                )
            )
            continue

        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            skipped_files.append(
                SkippedGitRepoFile(
                    repo_path=repo_path,
                    reason="binary or non-UTF-8 file",
                )
            )
            continue

        files.append(
            GitRepoFile(
                repo_path=repo_path,
                title=repo_path,
                canonical_id=f"{repo_url}@{commit_sha}:{repo_path}",
                source_url=repo_url,
                content=content,
            )
        )

    return GitRepoSnapshot(
        repo_dir=repo_dir,
        ref=resolved_ref,
        commit_sha=commit_sha,
        discovered_paths=discovered_paths,
        selected_paths=selected_paths,
        files=tuple(files),
        skipped_files=tuple(skipped_files),
    )


def normalize_subdir(subdir: str | None) -> str | None:
    """Normalize and validate an optional repository-relative subdirectory."""
    if subdir is None:
        return None

    normalized_value = subdir.strip().replace("\\", "/")
    if not normalized_value or normalized_value == ".":
        return None

    normalized_path = PurePosixPath(normalized_value)
    if normalized_path.is_absolute() or ".." in normalized_path.parts:
        raise ValueError(
            "Subdirectory must stay within the repository checkout. "
            "Use a relative path without '..'."
        )

    return normalized_path.as_posix()


def _ensure_repo_checkout(repo_url: str, repo_dir: Path) -> None:
    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            "clone",
            "--quiet",
            repo_url,
            str(repo_dir),
            operation=f"clone {repo_url!r}",
        )
        return

    if not (repo_dir / ".git").is_dir():
        raise ValueError(
            f"Cached git_repo checkout is not a git repository: {repo_dir}. "
            "Remove the cache directory and try again."
        )

    origin_url = _run_git(
        "remote",
        "get-url",
        "origin",
        cwd=repo_dir,
        operation="inspect cached origin URL",
    )
    if origin_url != repo_url:
        raise ValueError(
            f"Cached git_repo checkout at {repo_dir} points to {origin_url!r}, "
            f"not {repo_url!r}. Remove the cache directory and try again."
        )

    _run_git(
        "fetch",
        "--quiet",
        "--tags",
        "origin",
        cwd=repo_dir,
        operation=f"fetch {repo_url!r}",
    )


def _checkout_ref(repo_dir: Path, requested_ref: str | None) -> str:
    if requested_ref is None:
        default_branch = _default_branch(repo_dir)
        _run_git(
            "checkout",
            "--quiet",
            "--force",
            "--detach",
            f"origin/{default_branch}",
            cwd=repo_dir,
            operation=f"checkout default branch {default_branch!r}",
        )
        return default_branch

    for candidate in (requested_ref, f"origin/{requested_ref}"):
        if _git_ref_exists(repo_dir, candidate):
            _run_git(
                "checkout",
                "--quiet",
                "--force",
                "--detach",
                candidate,
                cwd=repo_dir,
                operation=f"checkout ref {requested_ref!r}",
            )
            return requested_ref

    _run_git(
        "fetch",
        "--quiet",
        "--tags",
        "origin",
        requested_ref,
        cwd=repo_dir,
        operation=f"fetch ref {requested_ref!r}",
    )
    for candidate in ("FETCH_HEAD", requested_ref, f"origin/{requested_ref}"):
        if _git_ref_exists(repo_dir, candidate):
            _run_git(
                "checkout",
                "--quiet",
                "--force",
                "--detach",
                candidate,
                cwd=repo_dir,
                operation=f"checkout ref {requested_ref!r}",
            )
            return requested_ref

    raise ValueError(f"Could not resolve git ref {requested_ref!r}.")


def _default_branch(repo_dir: Path) -> str:
    remote_head = _run_git(
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        cwd=repo_dir,
        operation="resolve default branch",
    )
    if not remote_head.startswith("origin/"):
        raise ValueError(f"Could not resolve default branch from {remote_head!r}.")
    return remote_head.removeprefix("origin/")


def _git_ref_exists(repo_dir: Path, candidate: str) -> bool:
    try:
        _run_git(
            "rev-parse",
            "--verify",
            "--quiet",
            f"{candidate}^{{commit}}",
            cwd=repo_dir,
            operation=f"resolve ref {candidate!r}",
        )
    except ValueError:
        return False
    return True


def _list_repo_files(repo_dir: Path, *, subdir: str | None) -> tuple[str, ...]:
    args = ["ls-files", "-z", "--cached", "--full-name"]
    if subdir is not None:
        args.extend(["--", subdir])

    output = _run_git(
        *args,
        cwd=repo_dir,
        operation="list tracked files",
    )
    if not output:
        return ()

    repo_paths = sorted(path for path in output.split("\x00") if path)
    return tuple(repo_paths)


def _path_is_selected(
    repo_path: str,
    *,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
) -> bool:
    repo_pure_path = PurePosixPath(repo_path)
    if include_patterns and not any(repo_pure_path.match(pattern) for pattern in include_patterns):
        return False
    if exclude_patterns and any(repo_pure_path.match(pattern) for pattern in exclude_patterns):
        return False
    return True


def _run_git(
    *args: str,
    cwd: Path | None = None,
    operation: str,
) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "System git is not available. Install git and try again."
        ) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "git command failed."
        raise ValueError(f"Could not {operation}: {detail}")
    return completed.stdout.strip()
