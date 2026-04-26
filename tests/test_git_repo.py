from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from pytest import CaptureFixture

from knowledge_adapters.cli import main
from knowledge_adapters.git_repo.writer import markdown_path
from tests.artifact_assertions import assert_markdown_document
from tests.cli_output_assertions import (
    assert_dry_run_summary,
    assert_stale_artifacts,
    assert_write_summary,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _commit_all(repo_dir: Path, message: str) -> str:
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "--quiet", "-m", message)
    return _git(repo_dir, "rev-parse", "HEAD")


def _init_repo(repo_dir: Path) -> None:
    repo_dir.mkdir()
    _git(repo_dir, "init", "--quiet", "--initial-branch=main")
    _git(repo_dir, "config", "commit.gpgsign", "false")
    _git(repo_dir, "config", "user.name", "Test User")
    _git(repo_dir, "config", "user.email", "test@example.com")


def _sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def test_git_repo_markdown_path_avoids_double_md_extension() -> None:
    assert markdown_path("/tmp/out", "README.md") == Path("/tmp/out/pages/README.md")
    assert markdown_path("/tmp/out", "docs/guide.txt") == Path("/tmp/out/pages/docs/guide.txt.md")


def test_git_repo_cli_writes_repo_files_with_manifest_metadata(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    repo_dir = tmp_path / "repo"
    _init_repo(repo_dir)
    _write_text(repo_dir / "README.md", "# Repo\n")
    _write_text(repo_dir / "docs" / "guide.txt", "Guide text.\n")
    _write_text(repo_dir / "src" / "module.py", "print('hello')\n")
    _write_bytes(repo_dir / "assets" / "logo.bin", b"\x00binary")
    commit_sha = _commit_all(repo_dir, "initial import")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "git_repo",
            "--repo-url",
            str(repo_dir),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Git repo adapter invoked" in captured.out
    assert f"repo_url: {repo_dir}" in captured.out
    assert f"output_dir: {output_dir.resolve()}" in captured.out
    assert "resolved_ref: main" in captured.out
    assert f"commit_sha: {commit_sha}" in captured.out
    assert "tracked_files: 4" in captured.out
    assert "selected_files: 4" in captured.out
    assert "filtered_out: 0" in captured.out
    assert "Skipped: assets/logo.bin (binary file)" in captured.out
    assert_write_summary(captured.out, wrote=3, skipped=1)
    assert f"Manifest path: {output_dir / 'manifest.json'}" in captured.out

    readme_output = output_dir / "pages" / "README.md"
    guide_output = output_dir / "pages" / "docs" / "guide.txt.md"
    module_output = output_dir / "pages" / "src" / "module.py.md"
    assert readme_output.exists()
    assert guide_output.exists()
    assert module_output.exists()

    assert_markdown_document(
        readme_output.read_text(encoding="utf-8"),
        title="README.md",
        metadata={
            "source": "git_repo",
            "canonical_id": f"{repo_dir}@{commit_sha}:README.md",
            "parent_id": "",
            "source_url": str(repo_dir),
            "fetched_at": "",
            "updated_at": "",
            "adapter": "git_repo",
        },
        content="# Repo",
    )

    manifest_payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    readme_hash = _sha256_text(readme_output)
    guide_hash = _sha256_text(guide_output)
    module_hash = _sha256_text(module_output)
    assert [entry["path"] for entry in manifest_payload["files"]] == [
        "README.md",
        "docs/guide.txt",
        "src/module.py",
    ]
    assert manifest_payload["files"] == [
        {
            "canonical_id": f"{repo_dir}@{commit_sha}:README.md",
            "source_url": str(repo_dir),
            "output_path": "pages/README.md",
            "title": "README.md",
            "content_hash": readme_hash,
            "path": "README.md",
            "ref": "main",
            "commit_sha": commit_sha,
        },
        {
            "canonical_id": f"{repo_dir}@{commit_sha}:docs/guide.txt",
            "source_url": str(repo_dir),
            "output_path": "pages/docs/guide.txt.md",
            "title": "docs/guide.txt",
            "content_hash": guide_hash,
            "path": "docs/guide.txt",
            "ref": "main",
            "commit_sha": commit_sha,
        },
        {
            "canonical_id": f"{repo_dir}@{commit_sha}:src/module.py",
            "source_url": str(repo_dir),
            "output_path": "pages/src/module.py.md",
            "title": "src/module.py",
            "content_hash": module_hash,
            "path": "src/module.py",
            "ref": "main",
            "commit_sha": commit_sha,
        },
    ]


def test_git_repo_cli_dry_run_respects_subdir_and_include_filters(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    repo_dir = tmp_path / "repo"
    _init_repo(repo_dir)
    _write_text(repo_dir / "docs" / "guide.md", "# Guide\n")
    _write_text(repo_dir / "docs" / "notes.txt", "Notes.\n")
    _write_text(repo_dir / "README.md", "# Root\n")
    _commit_all(repo_dir, "docs import")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "git_repo",
            "--repo-url",
            str(repo_dir),
            "--output-dir",
            str(output_dir),
            "--subdir",
            "docs",
            "--include",
            "*.md",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "subdir: docs" in captured.out
    assert "include: *.md" in captured.out
    assert "tracked_files: 2" in captured.out
    assert "selected_files: 1" in captured.out
    assert "filtered_out: 1" in captured.out
    assert "path: docs/guide.md" in captured.out
    assert "Artifact path: " in captured.out
    assert "pages/docs/guide.md" in captured.out
    assert_dry_run_summary(captured.out, would_write=1, would_skip=0)
    assert not output_dir.exists()


def test_git_repo_cli_uses_requested_ref_for_artifact_content_and_manifest(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    repo_dir = tmp_path / "repo"
    _init_repo(repo_dir)
    readme_path = repo_dir / "README.md"
    _write_text(readme_path, "# First version\n")
    first_commit = _commit_all(repo_dir, "first version")
    _git(repo_dir, "tag", "v1.0.0")
    _write_text(readme_path, "# Second version\n")
    _commit_all(repo_dir, "second version")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "git_repo",
            "--repo-url",
            str(repo_dir),
            "--ref",
            "v1.0.0",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "requested_ref: v1.0.0" in captured.out
    assert "resolved_ref: v1.0.0" in captured.out
    assert f"commit_sha: {first_commit}" in captured.out

    readme_output = output_dir / "pages" / "README.md"
    assert "# First version" in readme_output.read_text(encoding="utf-8")
    manifest_payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["files"][0]["ref"] == "v1.0.0"
    assert manifest_payload["files"][0]["commit_sha"] == first_commit


def test_git_repo_cli_reports_stale_artifacts_when_output_paths_change(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    repo_dir = tmp_path / "repo"
    _init_repo(repo_dir)
    _write_text(repo_dir / "README.md", "# Repo\n")
    commit_sha = _commit_all(repo_dir, "initial import")
    output_dir = tmp_path / "out"
    stale_output = output_dir / "pages" / "README.md.md"
    stale_output.parent.mkdir(parents=True, exist_ok=True)
    stale_output.write_text("legacy artifact\n", encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-20T00:00:00Z",
                "files": [
                    {
                        "canonical_id": f"{repo_dir}@{commit_sha}:README.md",
                        "source_url": str(repo_dir),
                        "output_path": "pages/README.md.md",
                        "title": "README.md",
                        "content_hash": "legacy-hash",
                        "path": "README.md",
                        "ref": "main",
                        "commit_sha": commit_sha,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "git_repo",
            "--repo-url",
            str(repo_dir),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert_write_summary(captured.out, wrote=1, skipped=0, stale_artifacts=1)
    assert_stale_artifacts(
        captured.out,
        count=1,
        artifact_paths=[stale_output],
    )
    assert stale_output.read_text(encoding="utf-8") == "legacy artifact\n"
    assert (output_dir / "pages" / "README.md").exists()


def test_git_repo_cli_dry_run_reports_stale_artifacts_when_files_disappear(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    repo_dir = tmp_path / "repo"
    _init_repo(repo_dir)
    _write_text(repo_dir / "README.md", "# Repo\n")
    _write_text(repo_dir / "docs" / "guide.txt", "Guide text.\n")
    _commit_all(repo_dir, "initial import")
    output_dir = tmp_path / "out"

    first_exit_code = main(
        [
            "git_repo",
            "--repo-url",
            str(repo_dir),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert first_exit_code == 0
    capsys.readouterr()

    stale_output = output_dir / "pages" / "docs" / "guide.txt.md"
    assert stale_output.exists()
    guide_contents = stale_output.read_text(encoding="utf-8")

    (repo_dir / "docs" / "guide.txt").unlink()
    _commit_all(repo_dir, "remove guide")

    exit_code = main(
        [
            "git_repo",
            "--repo-url",
            str(repo_dir),
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert_dry_run_summary(captured.out, would_write=1, would_skip=0)
    assert_stale_artifacts(
        captured.out,
        count=1,
        artifact_paths=[stale_output],
    )
    assert stale_output.read_text(encoding="utf-8") == guide_contents
    manifest_payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["path"] for entry in manifest_payload["files"]] == [
        "README.md",
        "docs/guide.txt",
    ]
