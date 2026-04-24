from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.cli_output_assertions import (
    assert_contains_normalized,
    assert_write_summary,
    normalize_whitespace,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cli_command() -> list[str]:
    repo_local_cli = _repo_root() / ".venv" / "bin" / "knowledge-adapters"
    if repo_local_cli.exists():
        return [str(repo_local_cli)]

    return [sys.executable, "-m", "knowledge_adapters.cli"]


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_cli_command(), *args],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )


def test_top_level_help_introduces_shared_cli_flow(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert "Normalize knowledge sources into a shared local artifact layout." in stdout
    assert "plans a markdown artifact under pages/ plus manifest.json" in stdout
    assert "Execute multiple configured adapter runs from one YAML file." in stdout
    assert "Normalize Confluence content into shared artifacts." in stdout
    assert "Normalize one local UTF-8 text file into shared artifacts." in stdout
    assert "Combine existing artifacts into one prompt-ready markdown file." in stdout
    assert (
        "Start with --dry-run to preview the source, artifact path, manifest path,"
        in stdout
    )
    assert "Re-run without --dry-run to write the same artifact layout" in stdout
    assert "knowledge-adapters run runs.yaml" in stdout
    assert "knowledge-adapters bundle ./artifacts --output ./bundle.md" in stdout


def test_local_files_cli_smoke_uses_installed_entrypoint_with_readme_style_args(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    source_file = notes_dir / "today.txt"
    source_file.write_text("Hello from smoke test.\n", encoding="utf-8")

    result = _run_cli(
        tmp_path,
        "local_files",
        "--file-path",
        "./notes/today.txt",
        "--output-dir",
        "./artifacts",
    )

    assert result.returncode == 0, result.stderr
    assert "Local files adapter invoked" in result.stdout
    assert f"file_path: {source_file.resolve()}" in result.stdout
    assert f"output_dir: {(tmp_path / 'artifacts').resolve()}" in result.stdout
    assert "run_mode: write" in result.stdout
    assert "Plan: Local files run" in result.stdout
    assert f"resolved_file_path: {source_file.resolve()}" in result.stdout
    assert f"source_url: {source_file.resolve().as_uri()}" in result.stdout
    assert f"Artifact path: {tmp_path / 'artifacts' / 'pages' / 'today.md'}" in result.stdout
    assert "Wrote:" in result.stdout
    assert_write_summary(result.stdout, wrote=1, skipped=0)
    assert f"Artifact path: {tmp_path / 'artifacts' / 'pages' / 'today.md'}" in result.stdout
    assert f"Manifest path: {tmp_path / 'artifacts' / 'manifest.json'}" in result.stdout
    assert f"Write complete. Artifacts created under {tmp_path / 'artifacts'}" in result.stdout

    output_path = tmp_path / "artifacts" / "pages" / "today.md"
    assert output_path.read_text(encoding="utf-8") == (
        f"""# today.txt

## Metadata
- source: local_files
- canonical_id: {source_file.resolve()}
- parent_id:
- source_url: {source_file.resolve().as_uri()}
- fetched_at:
- updated_at:
- adapter: local_files

## Content

Hello from smoke test.
"""
    )

    payload = json.loads((tmp_path / "artifacts" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["files"] == [
        {
            "canonical_id": str(source_file.resolve()),
            "source_url": source_file.resolve().as_uri(),
            "output_path": "pages/today.md",
            "title": "today.txt",
        }
    ]


def test_local_files_cli_help_includes_first_run_guidance(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "local_files", "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert (
        "Normalize one existing UTF-8 text file into the shared artifact layout."
        in stdout
    )
    assert "Empty UTF-8 files are allowed" in stdout
    assert "produce an empty content section." in stdout
    assert "Files that are not valid UTF-8 text are rejected" in stdout
    assert "directories are not supported" in stdout
    assert "--file-path FILE" in stdout
    assert "Path to the one existing local UTF-8 text file for this run." in stdout
    assert "Empty files are allowed; directories are not supported." in stdout
    assert "Relative paths" in stdout
    assert "resolve from the cwd." in stdout
    assert "--output-dir DIR" in stdout
    assert "Directory where pages/ and manifest.json are written." in stdout
    assert "local_files handles one file per run and always plans one write;" in stdout
    assert "it does not use manifest-based skip logic." in stdout
    assert "resolved file path, artifact path, manifest path" in stdout
    assert "without writing files." in stdout
    assert "knowledge-adapters local_files" in stdout
    assert "--dry-run" in stdout


def test_bundle_cli_help_includes_ordering_and_input_guidance(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "bundle", "--help")
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0, result.stderr
    assert "Combine existing artifacts into one prompt-ready markdown file." in stdout
    assert "one or more output directories or manifest files" in stdout
    assert "keeps the original artifacts unchanged" in stdout
    assert "selected deterministic ordering mode" in stdout
    assert "--output FILE" in stdout
    assert "--order {canonical_id,manifest,input}" in stdout
    assert "--header-mode {minimal,full}" in stdout
    assert "--include PATTERN" in stdout
    assert "--exclude PATTERN" in stdout
    assert "--max-bytes N" in stdout
    assert "--changed-only" in stdout
    assert "--baseline-manifest PATH" in stdout
    assert "canonical_id sorts lexically by canonical_id (default)" in stdout
    assert "manifest preserves manifest entry order" in stdout
    assert "input preserves bundle input order" in stdout
    assert "full includes source_url, canonical_id, and optional fetched_at," in stdout
    assert "path, and ref metadata when present (default)" in stdout
    assert "minimal includes only the title and source_url." in stdout
    assert "glob-style include and exclude filters match canonical_id, title," in stdout
    assert "output_path, and source_url" in stdout
    assert "Exclude filters apply after include matching and win on conflicts." in stdout
    assert "new or changed compared with --baseline-manifest" in stdout
    assert "compare by canonical_id and content_hash" in stdout
    assert "Split bundle output into numbered markdown files" in stdout
    assert "single oversized artifact is written to its own file and reported" in stdout
    assert "knowledge-adapters bundle ./artifacts/confluence --output ./bundle.md" in stdout
    assert (
        "knowledge-adapters bundle ./artifacts --header-mode minimal --output ./bundle.md"
        in stdout
    )
    assert '--include "team-*" --exclude "*draft*" --output ./bundle.md' in stdout
    assert "knowledge-adapters bundle ./artifacts --max-bytes 250000 --output ./bundle.md" in stdout


def test_bundle_cli_smoke_combines_multiple_inputs_in_deterministic_order(
    tmp_path: Path,
) -> None:
    output_a = tmp_path / "artifacts" / "a"
    output_b = tmp_path / "artifacts" / "b"
    (output_a / "pages").mkdir(parents=True)
    (output_b / "pages").mkdir(parents=True)
    (output_a / "pages" / "zeta.md").write_text(
        "# Zeta artifact\n\nZeta content.\n",
        encoding="utf-8",
    )
    (output_a / "pages" / "alpha.md").write_text(
        "# Alpha artifact\n\nAlpha content.\n",
        encoding="utf-8",
    )
    (output_b / "pages" / "alpha-copy.md").write_text(
        "# Alpha duplicate\n\nDuplicate content.\n",
        encoding="utf-8",
    )
    (output_b / "pages" / "beta.md").write_text(
        "# Beta artifact\n\nBeta content.\n",
        encoding="utf-8",
    )
    (output_a / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "zeta",
                        "source_url": "https://example.com/zeta",
                        "output_path": "pages/zeta.md",
                        "title": "Zeta",
                    },
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "title": "Alpha",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_b / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha-duplicate",
                        "output_path": "pages/alpha-copy.md",
                        "title": "Alpha duplicate",
                    },
                    {
                        "canonical_id": "beta",
                        "source_url": "https://example.com/beta",
                        "output_path": "pages/beta.md",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "bundle",
        "./artifacts/a",
        "./artifacts/b/manifest.json",
        "--output",
        "./bundles/llm.md",
    )

    assert result.returncode == 0, result.stderr
    assert "Bundle command invoked" in result.stdout
    assert "ordering: lexical canonical_id order" in result.stdout
    assert (
        "header_mode: title, source URL, canonical_id, and optional manifest metadata"
        in result.stdout
    )
    assert f"manifest: {output_a / 'manifest.json'}" in result.stdout
    assert f"manifest: {output_b / 'manifest.json'}" in result.stdout
    assert "artifacts_selected: 3" in result.stdout
    assert "duplicates_skipped: 1" in result.stdout
    assert f"Wrote bundle: {tmp_path / 'bundles' / 'llm.md'}" in result.stdout
    assert "Summary: bundled 3, skipped 1 duplicates" in result.stdout
    assert f"Write complete. Bundle created at {tmp_path / 'bundles' / 'llm.md'}" in result.stdout

    assert (tmp_path / "bundles" / "llm.md").read_text(encoding="utf-8") == (
        """## Alpha
source_url: https://example.com/alpha
canonical_id: alpha

# Alpha artifact

Alpha content.

---

## beta
source_url: https://example.com/beta
canonical_id: beta

# Beta artifact

Beta content.

---

## Zeta
source_url: https://example.com/zeta
canonical_id: zeta

# Zeta artifact

Zeta content.
"""
    )


def test_bundle_cli_smoke_supports_changed_only_against_baseline_manifest(
    tmp_path: Path,
) -> None:
    baseline_dir = tmp_path / "baseline"
    current_dir = tmp_path / "current"
    (baseline_dir / "pages").mkdir(parents=True)
    (current_dir / "pages").mkdir(parents=True)
    (baseline_dir / "pages" / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (baseline_dir / "pages" / "beta.md").write_text("# Beta old\n", encoding="utf-8")
    (current_dir / "pages" / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (current_dir / "pages" / "beta.md").write_text("# Beta new\n", encoding="utf-8")
    (current_dir / "pages" / "gamma.md").write_text("# Gamma\n", encoding="utf-8")
    (baseline_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "content_hash": "same-alpha",
                    },
                    {
                        "canonical_id": "beta",
                        "source_url": "https://example.com/beta",
                        "output_path": "pages/beta.md",
                        "content_hash": "old-beta",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (current_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "content_hash": "same-alpha",
                    },
                    {
                        "canonical_id": "beta",
                        "source_url": "https://example.com/beta",
                        "output_path": "pages/beta.md",
                        "content_hash": "new-beta",
                    },
                    {
                        "canonical_id": "gamma",
                        "source_url": "https://example.com/gamma",
                        "output_path": "pages/gamma.md",
                        "content_hash": "new-gamma",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "bundle",
        "./current",
        "--changed-only",
        "--baseline-manifest",
        "./baseline/manifest.json",
        "--output",
        "./bundles/changed.md",
    )

    assert result.returncode == 0, result.stderr
    assert "changed_only: true" in result.stdout
    assert f"baseline_manifest: {baseline_dir / 'manifest.json'}" in result.stdout
    assert "artifacts_selected: 2" in result.stdout
    assert "unchanged_skipped: 1" in result.stdout
    assert "Summary: bundled 2, skipped 1 unchanged, skipped 0 duplicates" in result.stdout
    assert (tmp_path / "bundles" / "changed.md").read_text(encoding="utf-8") == (
        """## beta
source_url: https://example.com/beta
canonical_id: beta

# Beta new

---

## gamma
source_url: https://example.com/gamma
canonical_id: gamma

# Gamma
"""
    )


def test_bundle_cli_smoke_splits_changed_only_output_into_numbered_files(
    tmp_path: Path,
) -> None:
    baseline_dir = tmp_path / "baseline"
    current_dir = tmp_path / "current"
    (baseline_dir / "pages").mkdir(parents=True)
    (current_dir / "pages").mkdir(parents=True)
    (baseline_dir / "pages" / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (baseline_dir / "pages" / "beta.md").write_text("# Beta old\n", encoding="utf-8")
    (current_dir / "pages" / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (current_dir / "pages" / "beta.md").write_text("# Beta new\n", encoding="utf-8")
    (current_dir / "pages" / "gamma.md").write_text("# Gamma\n", encoding="utf-8")
    (baseline_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "content_hash": "same-alpha",
                    },
                    {
                        "canonical_id": "beta",
                        "source_url": "https://example.com/beta",
                        "output_path": "pages/beta.md",
                        "content_hash": "old-beta",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (current_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "content_hash": "same-alpha",
                    },
                    {
                        "canonical_id": "beta",
                        "source_url": "https://example.com/beta",
                        "output_path": "pages/beta.md",
                        "content_hash": "new-beta",
                    },
                    {
                        "canonical_id": "gamma",
                        "source_url": "https://example.com/gamma",
                        "output_path": "pages/gamma.md",
                        "content_hash": "new-gamma",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "bundle",
        "./current",
        "--changed-only",
        "--baseline-manifest",
        "./baseline/manifest.json",
        "--max-bytes",
        "85",
        "--output",
        "./bundles/changed.md",
    )

    assert result.returncode == 0, result.stderr
    assert "changed_only: true" in result.stdout
    assert "max_bytes: 85" in result.stdout
    assert "output_files: 2" in result.stdout
    assert "Wrote split bundle files: 2" in result.stdout
    assert "Summary: bundled 2, skipped 1 unchanged, skipped 0 duplicates" in result.stdout
    assert "Summary: wrote 2 files, 0 oversized sections" in result.stdout
    assert f"First output path: {tmp_path / 'bundles' / 'changed-001.md'}" in result.stdout
    assert (tmp_path / "bundles" / "changed.md").exists() is False
    assert (tmp_path / "bundles" / "changed-001.md").read_text(encoding="utf-8") == (
        """## beta
source_url: https://example.com/beta
canonical_id: beta

# Beta new
"""
    )
    assert (tmp_path / "bundles" / "changed-002.md").read_text(encoding="utf-8") == (
        """## gamma
source_url: https://example.com/gamma
canonical_id: gamma

# Gamma
"""
    )


def test_bundle_cli_smoke_reports_oversized_split_section(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    (output_dir / "pages").mkdir(parents=True)
    (output_dir / "pages" / "alpha.md").write_text(
        "# Alpha\n\n" + ("A" * 160) + "\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "title": "Alpha",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "bundle",
        "./artifacts",
        "--max-bytes",
        "100",
        "--output",
        "./bundles/oversized.md",
    )

    assert result.returncode == 0, result.stderr
    assert "output_files: 1" in result.stdout
    assert "oversized_sections: 1" in result.stdout
    assert "oversized: alpha (" in result.stdout
    assert "bytes > 100 max)" in result.stdout
    assert "Summary: wrote 1 files, 1 oversized sections" in result.stdout
    assert (tmp_path / "bundles" / "oversized-001.md").stat().st_size > 100


def test_bundle_cli_smoke_supports_minimal_headers(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    (output_dir / "pages").mkdir(parents=True)
    (output_dir / "pages" / "alpha.md").write_text(
        "# Alpha artifact\n\nAlpha content.\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "title": "Alpha",
                        "fetched_at": "2026-04-24T12:00:00Z",
                        "path": "docs/alpha.md",
                        "ref": "refs/heads/main",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "bundle",
        "./artifacts",
        "--header-mode",
        "minimal",
        "--output",
        "./bundles/minimal.md",
    )

    assert result.returncode == 0, result.stderr
    assert "header_mode: title plus source URL" in result.stdout
    assert (tmp_path / "bundles" / "minimal.md").read_text(encoding="utf-8") == (
        """## Alpha
source_url: https://example.com/alpha

# Alpha artifact

Alpha content.
"""
    )


def test_bundle_cli_smoke_supports_input_ordering(tmp_path: Path) -> None:
    output_a = tmp_path / "artifacts" / "a"
    output_b = tmp_path / "artifacts" / "b"
    (output_a / "pages").mkdir(parents=True)
    (output_b / "pages").mkdir(parents=True)
    (output_a / "pages" / "gamma.md").write_text(
        "# Gamma artifact\n\nGamma content.\n",
        encoding="utf-8",
    )
    (output_a / "pages" / "alpha.md").write_text(
        "# Alpha artifact\n\nAlpha content from A.\n",
        encoding="utf-8",
    )
    (output_b / "pages" / "alpha-copy.md").write_text(
        "# Alpha duplicate\n\nAlpha content from B.\n",
        encoding="utf-8",
    )
    (output_b / "pages" / "beta.md").write_text(
        "# Beta artifact\n\nBeta content.\n",
        encoding="utf-8",
    )
    (output_a / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "gamma",
                        "source_url": "https://example.com/gamma",
                        "output_path": "pages/gamma.md",
                        "title": "Gamma",
                    },
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha-a",
                        "output_path": "pages/alpha.md",
                        "title": "Alpha from A",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_b / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha-b",
                        "output_path": "pages/alpha-copy.md",
                        "title": "Alpha from B",
                    },
                    {
                        "canonical_id": "beta",
                        "source_url": "https://example.com/beta",
                        "output_path": "pages/beta.md",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "bundle",
        "./artifacts/a",
        "./artifacts/b",
        "--order",
        "input",
        "--output",
        "./bundles/input-order.md",
    )

    assert result.returncode == 0, result.stderr
    assert "ordering: input order with manifest grouping" in result.stdout
    assert "duplicates_skipped: 1" in result.stdout
    assert (tmp_path / "bundles" / "input-order.md").read_text(encoding="utf-8") == (
        """## Gamma
source_url: https://example.com/gamma
canonical_id: gamma

# Gamma artifact

Gamma content.

---

## Alpha from A
source_url: https://example.com/alpha-a
canonical_id: alpha

# Alpha artifact

Alpha content from A.

---

## beta
source_url: https://example.com/beta
canonical_id: beta

# Beta artifact

Beta content.
"""
    )


def test_bundle_cli_smoke_supports_include_and_exclude_filters(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    (output_dir / "pages" / "docs").mkdir(parents=True)
    (output_dir / "pages" / "alpha.md").write_text(
        "# Alpha artifact\n\nAlpha content.\n",
        encoding="utf-8",
    )
    (output_dir / "pages" / "bravo.md").write_text(
        "# Bravo artifact\n\nBravo content.\n",
        encoding="utf-8",
    )
    (output_dir / "pages" / "docs" / "charlie.md").write_text(
        "# Charlie artifact\n\nCharlie content.\n",
        encoding="utf-8",
    )
    (output_dir / "pages" / "delta.md").write_text(
        "# Delta artifact\n\nDelta content.\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "alpha",
                        "source_url": "https://example.com/alpha",
                        "output_path": "pages/alpha.md",
                        "title": "Alpha",
                    },
                    {
                        "canonical_id": "bravo",
                        "source_url": "https://example.com/bravo",
                        "output_path": "pages/bravo.md",
                        "title": "Release notes",
                    },
                    {
                        "canonical_id": "charlie",
                        "source_url": "https://example.com/charlie",
                        "output_path": "pages/docs/charlie.md",
                        "title": "Charlie",
                    },
                    {
                        "canonical_id": "delta",
                        "source_url": "https://example.com/special/delta",
                        "output_path": "pages/delta.md",
                        "title": "Delta",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "bundle",
        "./artifacts",
        "--include",
        "Release*",
        "--include",
        "pages/docs/*",
        "--include",
        "https://example.com/special/*",
        "--exclude",
        "pages/docs/*",
        "--output",
        "./bundles/filtered.md",
    )

    assert result.returncode == 0, result.stderr
    assert "include_filters: 3" in result.stdout
    assert "exclude_filters: 1" in result.stdout
    assert "include: Release*" in result.stdout
    assert "include: pages/docs/*" in result.stdout
    assert "include: https://example.com/special/*" in result.stdout
    assert "exclude: pages/docs/*" in result.stdout
    assert "artifacts_selected: 2" in result.stdout
    assert "artifacts_filtered_out: 2" in result.stdout
    assert "Summary: bundled 2, filtered out 2, skipped 0 duplicates" in result.stdout
    assert (tmp_path / "bundles" / "filtered.md").read_text(encoding="utf-8") == (
        """## Release notes
source_url: https://example.com/bravo
canonical_id: bravo

# Bravo artifact

Bravo content.

---

## Delta
source_url: https://example.com/special/delta
canonical_id: delta

# Delta artifact

Delta content.
"""
    )


def test_run_cli_smoke_executes_multiple_sources_from_yaml(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    source_file = inputs_dir / "today.txt"
    source_file.write_text("Hello from config run.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/today.txt
    output_dir: ./artifacts/local/team-notes
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_path, "run", "./runs.yaml")

    assert result.returncode == 0, result.stderr
    assert "Config-driven run invoked" in result.stdout
    assert "Run 1/2 started: team-notes (local_files)" in result.stdout
    assert "Run 1/2 completed: team-notes (local_files)" in result.stdout
    assert "Run 2/2 started: docs-home (confluence)" in result.stdout
    assert "Run 2/2 completed: docs-home (confluence)" in result.stdout
    assert (
        result.stdout.index("Run 1/2 started: team-notes (local_files)")
        < result.stdout.index("Local files adapter invoked")
        < result.stdout.index("Run 1/2 completed: team-notes (local_files)")
    )
    assert "Aggregate summary:" in result.stdout
    assert "runs_completed: 2" in result.stdout
    assert "write_runs: 2" in result.stdout
    assert "dry_run_runs: 0" in result.stdout
    assert "wrote: 2" in result.stdout
    assert "skipped: 0" in result.stdout

    local_output_path = tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "today.md"
    assert local_output_path.exists()
    assert "Hello from config run." in local_output_path.read_text(encoding="utf-8")


def test_run_cli_smoke_supports_only_and_disabled_runs(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    source_file = inputs_dir / "today.txt"
    source_file.write_text("Hello from config run.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    enabled: false
  - name: team-notes
    type: local_files
    file_path: ./inputs/today.txt
    output_dir: ./artifacts/local/team-notes
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "67890"
    output_dir: ./artifacts/confluence/docs-tree
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_path, "run", "./runs.yaml", "--only", "docs-tree,docs-home")

    assert result.returncode == 0, result.stderr
    assert "only: docs-tree, docs-home" in result.stdout
    assert "runs_selected: 2" in result.stdout
    assert "runs_skipped_disabled: 0" in result.stdout
    assert "Run 1/2 started: docs-home (confluence)" in result.stdout
    assert "Run 2/2 started: docs-tree (confluence)" in result.stdout
    assert "Run 1/2 started: team-notes (local_files)" not in result.stdout
    assert not (tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "today.md").exists()


def test_run_cli_smoke_rejects_unknown_only_name(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/today.txt
    output_dir: ./artifacts/local/team-notes
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_path, "run", "./runs.yaml", "--only", "missing-run")

    assert result.returncode == 2
    assert result.stdout == ""
    assert (
        "knowledge-adapters run: error: Unknown run name(s) for --only in "
        f"{config_path.resolve()}: 'missing-run'. Available run names: 'team-notes'.\n"
    ) == result.stderr


def test_run_cli_smoke_rejects_invalid_confluence_config_before_execution(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    client_mode: preview
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_path, "run", "./runs.yaml")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Config-driven run invoked" not in result.stdout
    assert "Run 1/1:" not in result.stdout
    assert (
        "knowledge-adapters run: error: Run 'docs-home' in "
        f"{config_path.resolve()} has unsupported 'client_mode' value 'preview'. "
        "Use 'real' or 'stub'.\n"
    ) == result.stderr


def test_run_cli_smoke_continue_on_error_executes_later_runs_and_returns_non_zero(
    tmp_path: Path,
) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    source_file = inputs_dir / "today.txt"
    source_file.write_text("Hello from config run.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    client_mode: real
  - name: team-notes
    type: local_files
    file_path: ./inputs/today.txt
    output_dir: ./artifacts/local/team-notes
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_path, "run", "./runs.yaml", "--continue-on-error")

    assert result.returncode == 1
    assert "Run 1/2 started: docs-home (confluence)" in result.stdout
    assert "Run 1/2 failed: docs-home (confluence)" in result.stdout
    assert "Run 2/2 started: team-notes (local_files)" in result.stdout
    assert "Run 2/2 completed: team-notes (local_files)" in result.stdout
    assert "Aggregate summary:" in result.stdout
    assert "runs_completed: 1" in result.stdout
    assert "runs_failed: 1" in result.stdout
    assert "wrote: 1" in result.stdout
    assert "skipped: 0" in result.stdout
    assert "Config run completed with failures." in result.stdout
    assert "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while " in (
        result.stderr
    )
    assert "Missing Confluence bearer token." in result.stderr

    local_output_path = tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "today.md"
    assert local_output_path.exists()
    assert "Hello from config run." in local_output_path.read_text(encoding="utf-8")


def test_confluence_cli_smoke_uses_installed_entrypoint_with_default_stub_client(
    tmp_path: Path,
) -> None:
    result = _run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
    )

    assert result.returncode == 0, result.stderr
    assert "Confluence adapter invoked" in result.stdout
    assert f"output_dir: {(tmp_path / 'artifacts').resolve()}" in result.stdout
    assert "client_mode: stub" in result.stdout
    assert "content_source: scaffolded page content" in result.stdout
    assert "fetch_scope: page" in result.stdout
    assert "run_mode: write" in result.stdout
    assert "warning: stub mode ignores real-mode Confluence inputs:" not in result.stdout
    assert "Plan: Confluence run" in result.stdout
    assert "resolved_page_id: 12345" in result.stdout
    assert "Artifact:" in result.stdout
    assert "auth_method:" not in result.stdout
    assert "Wrote:" in result.stdout
    assert_write_summary(result.stdout, wrote=1, skipped=0)
    assert "Manifest:" in result.stdout
    assert f"Write complete. Artifacts created under {tmp_path / 'artifacts'}" in result.stdout

    output_path = tmp_path / "artifacts" / "pages" / "12345.md"
    assert output_path.read_text(encoding="utf-8") == (
        """# stub-page-12345

## Metadata
- source: confluence
- canonical_id: 12345
- parent_id:
- source_url: https://example.com/wiki/pages/viewpage.action?pageId=12345
- fetched_at:
- updated_at:
- adapter: confluence

## Content

Stub content for page 12345.
"""
    )

    payload = json.loads((tmp_path / "artifacts" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["files"] == [
        {
            "canonical_id": "12345",
            "source_url": "https://example.com/wiki/pages/viewpage.action?pageId=12345",
            "output_path": "pages/12345.md",
            "title": "stub-page-12345",
            "page_version": 1,
            "last_modified": "1970-01-01T00:00:00Z",
        }
    ]


def test_confluence_cli_tree_dry_run_with_stub_client_reports_discovery_limit(
    tmp_path: Path,
) -> None:
    result = _run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
        "--tree",
        "--max-depth",
        "1",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "client_mode: stub" in result.stdout
    assert "mode: tree" in result.stdout
    assert (
        "note: stub mode does not support descendant discovery; use --client-mode real "
        "to discover descendants from Confluence."
    ) in result.stdout


def test_confluence_cli_stub_mode_warns_when_real_only_inputs_are_ignored(
    tmp_path: Path,
) -> None:
    ca_bundle = tmp_path / "internal-ca.pem"
    ca_bundle.write_text("ca\n", encoding="utf-8")

    result = _run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
        "--auth-method",
        "client-cert-env",
        "--ca-bundle",
        str(ca_bundle),
    )

    assert result.returncode == 0, result.stderr
    assert (
        "warning: stub mode ignores real-mode Confluence inputs: --auth-method, "
        "--ca-bundle. Use --client-mode real to apply them."
    ) in result.stdout


def test_run_cli_smoke_surfaces_stub_mode_warning_for_ignored_confluence_real_inputs(
    tmp_path: Path,
) -> None:
    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    (certs_dir / "internal-ca.pem").write_text("ca\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    auth_method: client-cert-env
    ca_bundle: ./certs/internal-ca.pem
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_path, "run", "./runs.yaml")

    assert result.returncode == 0, result.stderr
    assert (
        "warning: stub mode ignores real-mode Confluence inputs: --auth-method, "
        "--ca-bundle. Use --client-mode real to apply them."
    ) in result.stdout


def test_confluence_cli_rejects_missing_tls_path_before_execution(
    tmp_path: Path,
) -> None:
    missing_ca_bundle = tmp_path / "missing-ca.pem"

    result = _run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
        "--ca-bundle",
        str(missing_ca_bundle),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "does not exist" in result.stderr
    assert str(missing_ca_bundle.resolve()) in result.stderr


def test_confluence_help_lists_supported_auth_methods_and_examples(
    tmp_path: Path,
) -> None:
    result = _run_cli(
        tmp_path,
        "confluence",
        "--help",
    )
    stdout = normalize_whitespace(result.stdout)

    assert result.returncode == 0
    assert "CONFLUENCE_BEARER_TOKEN" in stdout
    assert "CONFLUENCE_CLIENT_CERT_FILE" in stdout
    assert "client-cert-env" in stdout
    assert "--ca-bundle FILE" in stdout
    assert "overrides default certificate discovery" in stdout
    assert "--debug" in stdout
    assert "request debug details" in stdout
    assert "artifact layout and reporting" in stdout
    assert "page or, with --tree, a page tree" in stdout
    assert "planned artifact paths, manifest path, and write/skip decisions" in stdout
    assert_contains_normalized(stdout, "In tree mode, dry-run previews the root page and")
    assert "artifact paths used in write mode" in stdout
    assert "same resolve, plan, and write flow" in stdout
    assert "'real' fetches from" in stdout
    assert "using --auth-method" in stdout
    assert "contract-tested live fetches" in stdout
    assert "The CLI resolves either input into one canonical page" in stdout
    assert "source URL for artifact and manifest reporting" in stdout
    assert "artifact and manifest reporting" in stdout
    assert "Traverse the resolved root page and discovered" in stdout
    assert "descendants instead of only one page." in stdout
    assert "Maximum descendant depth for --tree." in stdout
    assert "Ignored unless --tree is set." in stdout
    assert "CONFLUENCE_BEARER_TOKEN=... knowledge-adapters confluence" in stdout
    assert "--max-depth 1" in stdout
    assert "--dry-run" in stdout


def test_confluence_cli_rejects_invalid_base_url_before_planning(tmp_path: Path) -> None:
    result = _run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "ftp://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Plan: Confluence run" not in result.stdout
    assert "Confluence adapter invoked" not in result.stdout
    assert (
        "knowledge-adapters confluence: error: --base-url 'ftp://example.com/wiki' "
        "is invalid. Provide a full http:// or https:// Confluence base URL, for "
        "example 'https://example.com/wiki'.\n"
    ) == result.stderr
