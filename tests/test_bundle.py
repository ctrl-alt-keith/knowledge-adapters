from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_adapters.bundle import (
    DEFAULT_BUNDLE_ORDER,
    ORDERING_RULE,
    describe_bundle_order,
    load_bundle_plan,
    render_bundle_markdown,
    write_bundle,
)


def _write_output_dir(
    output_dir: Path,
    *,
    files: list[dict[str, object]],
    artifact_contents: dict[str, str],
) -> Path:
    (output_dir / "pages").mkdir(parents=True, exist_ok=True)
    for relative_path, content in artifact_contents.items():
        artifact_path = output_dir / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(content, encoding="utf-8")

    manifest = output_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-24T00:00:00Z",
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
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


def test_write_bundle_creates_parent_directories(tmp_path: Path) -> None:
    output_path = write_bundle(tmp_path / "bundles" / "llm.md", "bundle\n")

    assert output_path == tmp_path / "bundles" / "llm.md"
    assert output_path.read_text(encoding="utf-8") == "bundle\n"
