from __future__ import annotations

import json
from pathlib import Path

from tests.cli_helpers import run_cli
from tests.cli_output_assertions import normalize_whitespace


def test_bundle_cli_help_includes_ordering_and_input_guidance(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "bundle", "--help")
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
        "knowledge-adapters bundle ./artifacts --header-mode minimal --output ./bundle.md" in stdout
    )
    assert '--include "team-*" --exclude "*draft*" --output ./bundle.md' in stdout
    assert "knowledge-adapters bundle ./artifacts --max-bytes 250000 --output ./bundle.md" in stdout


def test_bundle_cli_combines_multiple_inputs_in_deterministic_order(
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

    result = run_cli(
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


def test_bundle_cli_supports_changed_only_against_baseline_manifest(
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

    result = run_cli(
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


def test_bundle_cli_splits_changed_only_output_into_numbered_files(
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

    result = run_cli(
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


def test_bundle_cli_reports_oversized_split_section(tmp_path: Path) -> None:
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

    result = run_cli(
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


def test_bundle_cli_supports_minimal_headers(tmp_path: Path) -> None:
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

    result = run_cli(
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


def test_bundle_cli_supports_input_ordering(tmp_path: Path) -> None:
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

    result = run_cli(
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


def test_bundle_cli_supports_include_and_exclude_filters(tmp_path: Path) -> None:
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

    result = run_cli(
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
