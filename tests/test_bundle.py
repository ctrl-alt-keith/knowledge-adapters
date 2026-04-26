from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import CaptureFixture

from knowledge_adapters.bundle import (
    DEFAULT_BUNDLE_ORDER,
    DEFAULT_HEADER_MODE,
    DEFAULT_STALE_MODE,
    ORDERING_RULE,
    StaleMode,
    describe_bundle_order,
    describe_stale_mode,
    load_bundle_plan,
    plan_split_bundle,
    render_bundle_markdown,
    render_bundle_sections,
    write_bundle,
    write_split_bundle,
)
from knowledge_adapters.cli import main


def _write_output_dir(
    output_dir: Path,
    *,
    files: list[dict[str, object]],
    artifact_contents: dict[str, str],
    stale_artifacts: list[dict[str, object]] | None = None,
) -> Path:
    (output_dir / "pages").mkdir(parents=True, exist_ok=True)
    for relative_path, content in artifact_contents.items():
        artifact_path = output_dir / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(content, encoding="utf-8")

    manifest = output_dir / "manifest.json"
    payload: dict[str, object] = {
        "generated_at": "2026-04-24T00:00:00Z",
        "files": files,
    }
    if stale_artifacts is not None:
        payload["stale_artifacts"] = stale_artifacts
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def test_load_bundle_plan_deduplicates_inputs_and_sorts_by_canonical_id(tmp_path: Path) -> None:
    output_a = tmp_path / "artifacts" / "a"
    output_b = tmp_path / "artifacts" / "b"
    manifest_b = _write_output_dir(
        output_b,
        files=[
            {
                "canonical_id": "gamma",
                "source_url": "https://example.com/gamma",
                "output_path": "pages/gamma.md",
                "title": "Gamma",
            },
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha-b",
                "output_path": "pages/alpha-b.md",
                "title": "Alpha from B",
            },
        ],
        artifact_contents={
            "pages/gamma.md": "# Gamma\n\nGamma content.\n",
            "pages/alpha-b.md": "# Alpha from B\n\nAlpha content from B.\n",
        },
    )
    _write_output_dir(
        output_a,
        files=[
            {
                "canonical_id": "zeta",
                "source_url": "https://example.com/zeta",
                "output_path": "pages/zeta.md",
                "title": "Zeta",
            },
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha-a",
                "output_path": "pages/alpha-a.md",
                "title": "Alpha from A",
            },
        ],
        artifact_contents={
            "pages/zeta.md": "# Zeta\n\nZeta content.\n",
            "pages/alpha-a.md": "# Alpha from A\n\nAlpha content from A.\n",
        },
    )

    plan = load_bundle_plan((output_a, manifest_b))

    assert plan.manifests == (output_a / "manifest.json", manifest_b)
    assert [artifact.canonical_id for artifact in plan.artifacts] == ["alpha", "gamma", "zeta"]
    assert [artifact.title for artifact in plan.artifacts] == ["Alpha from A", "Gamma", "Zeta"]
    assert plan.duplicate_canonical_ids == ("alpha",)
    assert ORDERING_RULE == "lexical canonical_id order"
    assert DEFAULT_BUNDLE_ORDER == "canonical_id"
    assert describe_bundle_order(DEFAULT_BUNDLE_ORDER) == ORDERING_RULE


def test_load_bundle_plan_preserves_manifest_entry_order_when_requested(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "gamma",
                "source_url": "https://example.com/gamma",
                "output_path": "pages/gamma.md",
            },
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
            },
            {
                "canonical_id": "zeta",
                "source_url": "https://example.com/zeta",
                "output_path": "pages/zeta.md",
            },
        ],
        artifact_contents={
            "pages/gamma.md": "# Gamma\n",
            "pages/alpha.md": "# Alpha\n",
            "pages/zeta.md": "# Zeta\n",
        },
    )

    plan = load_bundle_plan((output_dir,), order="manifest")

    assert [artifact.canonical_id for artifact in plan.artifacts] == ["gamma", "alpha", "zeta"]


def test_load_bundle_plan_preserves_input_grouping_and_first_wins_duplicates(
    tmp_path: Path,
) -> None:
    output_a = tmp_path / "artifacts" / "a"
    output_b = tmp_path / "artifacts" / "b"
    _write_output_dir(
        output_a,
        files=[
            {
                "canonical_id": "zeta",
                "source_url": "https://example.com/zeta",
                "output_path": "pages/zeta.md",
                "title": "Zeta",
            },
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha-a",
                "output_path": "pages/alpha.md",
                "title": "Alpha from A",
            },
        ],
        artifact_contents={
            "pages/zeta.md": "# Zeta\n",
            "pages/alpha.md": "# Alpha from A\n",
        },
    )
    _write_output_dir(
        output_b,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha-b",
                "output_path": "pages/alpha-duplicate.md",
                "title": "Alpha from B",
            },
            {
                "canonical_id": "beta",
                "source_url": "https://example.com/beta",
                "output_path": "pages/beta.md",
                "title": "Beta",
            },
        ],
        artifact_contents={
            "pages/alpha-duplicate.md": "# Alpha from B\n",
            "pages/beta.md": "# Beta\n",
        },
    )

    plan = load_bundle_plan((output_a, output_b), order="input")

    assert [artifact.canonical_id for artifact in plan.artifacts] == ["zeta", "alpha", "beta"]
    assert [artifact.title for artifact in plan.artifacts] == ["Zeta", "Alpha from A", "Beta"]
    assert plan.duplicate_canonical_ids == ("alpha",)


def test_load_bundle_plan_changed_only_selects_new_and_changed_artifacts(
    tmp_path: Path,
) -> None:
    baseline_dir = tmp_path / "baseline"
    baseline_manifest = _write_output_dir(
        baseline_dir,
        files=[
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
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
            "pages/beta.md": "# Beta old\n",
        },
    )
    current_dir = tmp_path / "current"
    _write_output_dir(
        current_dir,
        files=[
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
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
            "pages/beta.md": "# Beta new\n",
            "pages/gamma.md": "# Gamma\n",
        },
    )

    plan = load_bundle_plan(
        (current_dir,),
        changed_only=True,
        baseline_manifest=baseline_manifest,
    )

    assert [artifact.canonical_id for artifact in plan.artifacts] == ["beta", "gamma"]
    assert plan.unchanged_count == 1
    assert plan.baseline_manifest == baseline_manifest


def test_load_bundle_plan_changed_only_uses_file_hashes_when_manifest_hashes_are_absent(
    tmp_path: Path,
) -> None:
    baseline_dir = tmp_path / "baseline"
    baseline_manifest = _write_output_dir(
        baseline_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
            },
            {
                "canonical_id": "beta",
                "source_url": "https://example.com/beta",
                "output_path": "pages/beta.md",
            },
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
            "pages/beta.md": "# Beta old\n",
        },
    )
    current_dir = tmp_path / "current"
    _write_output_dir(
        current_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
            },
            {
                "canonical_id": "beta",
                "source_url": "https://example.com/beta",
                "output_path": "pages/beta.md",
            },
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
            "pages/beta.md": "# Beta new\n",
        },
    )

    plan = load_bundle_plan(
        (current_dir,),
        changed_only=True,
        baseline_manifest=baseline_manifest,
    )

    assert [artifact.canonical_id for artifact in plan.artifacts] == ["beta"]
    assert plan.unchanged_count == 1


def test_load_bundle_plan_changed_only_treats_missing_baseline_file_as_changed(
    tmp_path: Path,
) -> None:
    baseline_dir = tmp_path / "baseline"
    baseline_manifest = _write_output_dir(
        baseline_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "content_hash": "same-alpha",
            }
        ],
        artifact_contents={},
    )
    current_dir = tmp_path / "current"
    _write_output_dir(
        current_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "content_hash": "same-alpha",
            }
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
        },
    )

    plan = load_bundle_plan(
        (current_dir,),
        changed_only=True,
        baseline_manifest=baseline_manifest,
    )

    assert [artifact.canonical_id for artifact in plan.artifacts] == ["alpha"]
    assert plan.unchanged_count == 0


def test_bundle_stale_mode_is_ignored_without_explicit_stale_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            }
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
        },
    )

    default_plan = load_bundle_plan((output_dir,))
    flagged_plan = load_bundle_plan((output_dir,), stale_mode="flag")

    assert DEFAULT_STALE_MODE == "include"
    assert default_plan.stale_metadata_available is False
    assert flagged_plan.stale_metadata_available is False
    assert default_plan.stale_artifact_count == 0
    assert [artifact.canonical_id for artifact in flagged_plan.artifacts] == ["alpha"]
    assert render_bundle_markdown(flagged_plan.artifacts, stale_mode="flag") == (
        render_bundle_markdown(default_plan.artifacts)
    )


@pytest.mark.parametrize(
    ("stale_mode", "expected_ids", "expected_excluded", "expected_flagged"),
    [
        ("include", ["alpha", "legacy"], 0, 0),
        ("exclude", ["alpha"], 1, 0),
        ("flag", ["alpha", "legacy"], 0, 1),
    ],
)
def test_load_bundle_plan_handles_explicit_stale_metadata_by_mode(
    tmp_path: Path,
    stale_mode: StaleMode,
    expected_ids: list[str],
    expected_excluded: int,
    expected_flagged: int,
) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            }
        ],
        stale_artifacts=[
            {
                "canonical_id": "legacy",
                "source_url": "https://example.com/legacy",
                "output_path": "pages/legacy.md",
                "title": "Legacy",
            }
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
            "pages/legacy.md": "# Legacy\n\nLegacy content.\n",
        },
    )

    first_plan = load_bundle_plan((output_dir,), stale_mode=stale_mode)
    second_plan = load_bundle_plan((output_dir,), stale_mode=stale_mode)

    assert first_plan.stale_metadata_available is True
    assert first_plan.stale_artifact_count == 1
    assert first_plan.stale_artifacts_excluded_count == expected_excluded
    assert first_plan.stale_artifacts_flagged_count == expected_flagged
    assert [artifact.canonical_id for artifact in first_plan.artifacts] == expected_ids
    assert [artifact.canonical_id for artifact in second_plan.artifacts] == expected_ids
    assert render_bundle_markdown(
        first_plan.artifacts,
        stale_mode=stale_mode,
    ) == render_bundle_markdown(
        second_plan.artifacts,
        stale_mode=stale_mode,
    )


def test_render_bundle_markdown_flags_stale_artifacts_when_requested(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            },
            {
                "canonical_id": "legacy",
                "source_url": "https://example.com/legacy",
                "output_path": "pages/legacy.md",
                "title": "Legacy",
                "stale": True,
            },
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
            "pages/legacy.md": "# Legacy\n\nLegacy content.\n",
        },
    )

    plan = load_bundle_plan((output_dir,), stale_mode="flag")

    assert render_bundle_markdown(plan.artifacts, stale_mode="flag") == (
        """## Alpha
source_url: https://example.com/alpha
canonical_id: alpha

# Alpha

Alpha content.

---

## Legacy
source_url: https://example.com/legacy
stale: true
canonical_id: legacy

# Legacy

Legacy content.
"""
    )


def test_bundle_cli_reports_stale_handling_when_metadata_is_available(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "artifacts"
    bundle_path = tmp_path / "bundle.md"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            },
            {
                "canonical_id": "legacy",
                "source_url": "https://example.com/legacy",
                "output_path": "pages/legacy.md",
                "title": "Legacy",
                "stale": True,
            },
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
            "pages/legacy.md": "# Legacy\n",
        },
    )

    exit_code = main(
        [
            "bundle",
            str(output_dir),
            "--output",
            str(bundle_path),
            "--stale-mode",
            "exclude",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert describe_stale_mode("exclude") in captured.out
    assert "stale_artifacts: 1" in captured.out
    assert "stale_artifacts_excluded: 1" in captured.out
    assert "Summary: bundled 1, skipped 0 duplicates" in captured.out
    assert "Legacy" not in bundle_path.read_text(encoding="utf-8")


def test_bundle_cli_renders_named_bundle_from_config_for_one_run(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "artifacts" / "team-notes"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "team-notes",
                "source_url": "https://example.com/team-notes",
                "output_path": "pages/team-notes.md",
                "title": "Team Notes",
            }
        ],
        artifact_contents={
            "pages/team-notes.md": "# Team Notes\n\nShip it.\n",
        },
    )
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/team-notes
bundles:
  - name: review-pack
    runs: team-notes
    output: ./bundles/review-pack.md
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["bundle", "--config", str(config_path), "--bundle", "review-pack"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "bundle: review-pack" in captured.out
    assert "config_path:" in captured.out
    bundle_path = tmp_path / "bundles" / "review-pack.md"
    assert bundle_path.exists()
    assert "Team Notes" in bundle_path.read_text(encoding="utf-8")


def test_bundle_cli_renders_named_bundle_from_config_with_multiple_runs_and_options(
    tmp_path: Path,
) -> None:
    output_a = tmp_path / "artifacts" / "a"
    output_b = tmp_path / "artifacts" / "b"
    _write_output_dir(
        output_a,
        files=[
            {
                "canonical_id": "gamma",
                "source_url": "https://example.com/gamma",
                "output_path": "pages/gamma.md",
                "title": "Gamma",
            },
            {
                "canonical_id": "draft",
                "source_url": "https://example.com/draft",
                "output_path": "pages/draft.md",
                "title": "Draft",
            },
        ],
        artifact_contents={
            "pages/gamma.md": "# Gamma\n\nGamma content.\n",
            "pages/draft.md": "# Draft\n\nDraft content.\n",
        },
    )
    _write_output_dir(
        output_b,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            }
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
        },
    )
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: run-a
    type: local_files
    file_path: ./inputs/a.txt
    output_dir: ./artifacts/a
  - name: run-b
    type: local_files
    file_path: ./inputs/b.txt
    output_dir: ./artifacts/b
bundles:
  - name: review-pack
    runs:
      - run-a
      - run-b
    output: ./bundles/review-pack.md
    order: input
    header_mode: minimal
    exclude:
      - draft
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["bundle", "--config", str(config_path), "--bundle", "review-pack"])

    assert exit_code == 0
    bundle_path = tmp_path / "bundles" / "review-pack.md"
    bundle_text = bundle_path.read_text(encoding="utf-8")
    assert bundle_text.startswith("## Gamma\n")
    assert "\n---\n\n## Alpha\n" in bundle_text
    assert "## Draft\n" not in bundle_text
    assert "canonical_id:" not in bundle_text


def test_bundle_cli_rejects_unknown_named_bundle_name(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/team-notes
bundles:
  - name: review-pack
    runs: team-notes
    output: ./bundles/review-pack.md
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="2"):
        main(["bundle", "--config", str(config_path), "--bundle", "missing-bundle"])

    captured = capsys.readouterr()
    assert "Unknown bundle name 'missing-bundle'" in captured.err


def test_load_bundle_plan_changed_only_requires_baseline_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
            }
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
        },
    )

    with pytest.raises(ValueError, match="requires --baseline-manifest"):
        load_bundle_plan((output_dir,), changed_only=True)


def test_load_bundle_plan_supports_repeated_include_patterns_across_metadata_fields(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
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
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
            "pages/bravo.md": "# Bravo\n",
            "pages/docs/charlie.md": "# Charlie\n",
            "pages/delta.md": "# Delta\n",
        },
    )

    plan = load_bundle_plan(
        (output_dir,),
        include_patterns=(
            "alpha",
            "Release*",
            "pages/docs/*",
            "https://example.com/special/*",
        ),
    )

    assert [artifact.canonical_id for artifact in plan.artifacts] == [
        "alpha",
        "bravo",
        "charlie",
        "delta",
    ]
    assert plan.filtered_out_count == 0


def test_load_bundle_plan_applies_repeated_excludes_after_include_matching(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
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
                "title": "Bravo",
            },
            {
                "canonical_id": "charlie",
                "source_url": "https://example.com/charlie",
                "output_path": "pages/docs/charlie.md",
                "title": "Charlie",
            },
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n",
            "pages/bravo.md": "# Bravo\n",
            "pages/docs/charlie.md": "# Charlie\n",
        },
    )

    plan = load_bundle_plan(
        (output_dir,),
        include_patterns=("alpha", "bravo", "pages/docs/*"),
        exclude_patterns=("bravo", "pages/docs/*"),
    )

    assert [artifact.canonical_id for artifact in plan.artifacts] == ["alpha"]
    assert plan.filtered_out_count == 2


def test_render_bundle_markdown_reads_selected_artifacts_with_separators(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "beta",
                "source_url": "https://example.com/beta",
                "output_path": "pages/beta.md",
            },
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            },
        ],
        artifact_contents={
            "pages/beta.md": "# Beta\n\nBeta content.\n",
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
        },
    )

    plan = load_bundle_plan((output_dir,))

    assert DEFAULT_HEADER_MODE == "full"
    assert render_bundle_markdown(plan.artifacts) == (
        """## Alpha
source_url: https://example.com/alpha
canonical_id: alpha

# Alpha

Alpha content.

---

## beta
source_url: https://example.com/beta
canonical_id: beta

# Beta

Beta content.
"""
    )


def test_render_bundle_markdown_supports_minimal_headers(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "beta",
                "source_url": "https://example.com/beta",
                "output_path": "pages/beta.md",
            },
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
                "fetched_at": "2026-04-24T12:00:00Z",
                "path": "docs/alpha.md",
                "ref": "refs/heads/main",
            },
        ],
        artifact_contents={
            "pages/beta.md": "# Beta\n\nBeta content.\n",
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
        },
    )

    plan = load_bundle_plan((output_dir,))

    assert render_bundle_markdown(plan.artifacts, header_mode="minimal") == (
        """## Alpha
source_url: https://example.com/alpha

# Alpha

Alpha content.

---

## beta
source_url: https://example.com/beta

# Beta

Beta content.
"""
    )


def test_render_bundle_markdown_includes_optional_full_header_metadata_when_present(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
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
        artifact_contents={
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
        },
    )

    plan = load_bundle_plan((output_dir,))

    assert render_bundle_markdown(plan.artifacts) == (
        """## Alpha
source_url: https://example.com/alpha
canonical_id: alpha
fetched_at: 2026-04-24T12:00:00Z
path: docs/alpha.md
ref: refs/heads/main

# Alpha

Alpha content.
"""
    )


def test_render_bundle_markdown_rejects_missing_artifact_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
            }
        ],
        artifact_contents={},
    )

    plan = load_bundle_plan((output_dir,))

    with pytest.raises(ValueError, match="Could not read artifact for canonical_id 'alpha'"):
        render_bundle_markdown(plan.artifacts)


def test_plan_split_bundle_writes_deterministic_numbered_files_between_sections(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "draft",
                "source_url": "https://example.com/draft",
                "output_path": "pages/draft.md",
                "title": "Draft",
            },
            {
                "canonical_id": "gamma",
                "source_url": "https://example.com/gamma",
                "output_path": "pages/gamma.md",
                "title": "Gamma",
            },
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            },
            {
                "canonical_id": "beta",
                "source_url": "https://example.com/beta",
                "output_path": "pages/beta.md",
                "title": "Beta",
            },
        ],
        artifact_contents={
            "pages/draft.md": "# Draft\n\nDraft content.\n",
            "pages/gamma.md": "# Gamma\n\nGamma content.\n",
            "pages/alpha.md": "# Alpha\n\nAlpha content.\n",
            "pages/beta.md": "# Beta\n\nBeta content.\n",
        },
    )

    bundle_plan = load_bundle_plan((output_dir,), order="input", exclude_patterns=("draft",))
    split_plan = plan_split_bundle(
        tmp_path / "bundles" / "llm.md",
        render_bundle_sections(bundle_plan.artifacts, header_mode="minimal"),
        max_bytes=95,
    )

    assert [output_file.path.name for output_file in split_plan.output_files] == [
        "llm-001.md",
        "llm-002.md",
        "llm-003.md",
    ]
    assert [output_file.artifact_count for output_file in split_plan.output_files] == [1, 1, 1]
    assert bundle_plan.filtered_out_count == 1
    assert split_plan.oversized_sections == ()

    write_split_bundle(split_plan)

    assert (tmp_path / "bundles" / "llm.md").exists() is False
    assert (tmp_path / "bundles" / "llm-001.md").read_text(encoding="utf-8") == (
        """## Gamma
source_url: https://example.com/gamma

# Gamma

Gamma content.
"""
    )
    assert "canonical_id:" not in (tmp_path / "bundles" / "llm-001.md").read_text(encoding="utf-8")
    assert (
        (tmp_path / "bundles" / "llm-002.md").read_text(encoding="utf-8").startswith("## Alpha\n")
    )
    assert (tmp_path / "bundles" / "llm-003.md").read_text(encoding="utf-8").startswith("## Beta\n")


def test_plan_split_bundle_writes_oversized_single_artifact_as_own_file(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "artifacts"
    _write_output_dir(
        output_dir,
        files=[
            {
                "canonical_id": "alpha",
                "source_url": "https://example.com/alpha",
                "output_path": "pages/alpha.md",
                "title": "Alpha",
            },
            {
                "canonical_id": "beta",
                "source_url": "https://example.com/beta",
                "output_path": "pages/beta.md",
                "title": "Beta",
            },
        ],
        artifact_contents={
            "pages/alpha.md": "# Alpha\n\n" + ("A" * 180) + "\n",
            "pages/beta.md": "# Beta\n\nBeta content.\n",
        },
    )

    bundle_plan = load_bundle_plan((output_dir,))
    split_plan = plan_split_bundle(
        tmp_path / "bundle.md",
        render_bundle_sections(bundle_plan.artifacts),
        max_bytes=120,
    )

    assert [output_file.path.name for output_file in split_plan.output_files] == [
        "bundle-001.md",
        "bundle-002.md",
    ]
    assert [output_file.artifact_count for output_file in split_plan.output_files] == [1, 1]
    assert [section.canonical_id for section in split_plan.oversized_sections] == ["alpha"]
    assert split_plan.oversized_sections[0].byte_count > 120

    write_split_bundle(split_plan)

    assert (tmp_path / "bundle-001.md").stat().st_size > 120
    assert (tmp_path / "bundle-001.md").read_text(encoding="utf-8").startswith("## Alpha\n")
    assert (tmp_path / "bundle-002.md").stat().st_size <= 120


def test_write_bundle_creates_parent_directories(tmp_path: Path) -> None:
    output_path = write_bundle(tmp_path / "bundles" / "llm.md", "bundle\n")

    assert output_path == tmp_path / "bundles" / "llm.md"
    assert output_path.read_text(encoding="utf-8") == "bundle\n"
