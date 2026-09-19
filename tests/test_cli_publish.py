"""Regression coverage for explicit configured Google Docs publication."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pytest import CaptureFixture, MonkeyPatch

import knowledge_adapters.cli as cli
from knowledge_adapters import google_docs


def _write_config(tmp_path: Path, *, title: str | None = None) -> Path:
    (tmp_path / "input.txt").write_text("source", encoding="utf-8")
    bundle = tmp_path / "artifacts" / "my-review-pack.md"
    bundle.parent.mkdir()
    bundle.write_text("# Review\n", encoding="utf-8")
    title_line = f"    title: {title}\n" if title is not None else ""
    config = tmp_path / "runs.yaml"
    config.write_text(
        "runs:\n"
        "  - name: source\n"
        "    type: local_files\n"
        "    file_path: ./input.txt\n"
        "    output_dir: ./artifacts/source\n"
        "bundles:\n"
        "  - name: review-pack\n"
        "    runs: source\n"
        "    output: ./artifacts/my-review-pack.md\n"
        "publishes:\n"
        "  - name: review-pack-doc\n"
        "    bundle: review-pack\n"
        f"{title_line}",
        encoding="utf-8",
    )
    return config


def test_publish_dry_run_derives_title_from_bundle_filename(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)

    result = cli.main(
        [
            "publish",
            "--config",
            str(config),
            "--publish",
            "review-pack-doc",
            "--dry-run",
            "--output-format",
            "json",
        ]
    )

    assert result == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["title"] == "my-review-pack"
    assert receipt["dry_run"] is True


def test_explicit_publish_title_overrides_derived_default(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config = _write_config(tmp_path, title="Explicit title")
    publish = Mock(return_value="https://docs.google.com/document/d/doc-id/edit")
    monkeypatch.setattr(google_docs, "publish_markdown", publish)

    result = cli.main(["publish", "--config", str(config), "--publish", "review-pack-doc"])

    assert result == 0
    assert publish.call_args.kwargs["title"] == "Explicit title"


def test_run_does_not_publish_configured_entries(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = _write_config(tmp_path)
    publish = Mock()
    monkeypatch.setattr(google_docs, "publish_markdown", publish)

    result = cli.main(["run", str(config), "--dry-run"])

    assert result == 0
    publish.assert_not_called()


def test_bundle_does_not_publish_configured_entries(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config = _write_config(tmp_path)
    publish = Mock()
    monkeypatch.setattr(google_docs, "publish_markdown", publish)

    assert cli.main(["run", str(config)]) == 0
    assert cli.main(["bundle", "--config", str(config)]) == 0

    publish.assert_not_called()


def test_publish_reads_the_existing_bundle_without_rendering_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config = _write_config(tmp_path)
    bundle_path = tmp_path / "artifacts" / "my-review-pack.md"
    bundle_path.unlink()
    publish = Mock()
    monkeypatch.setattr(google_docs, "publish_markdown", publish)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["publish", "--config", str(config), "--publish", "review-pack-doc"])

    assert exit_info.value.code == 2
    assert not bundle_path.exists()
    publish.assert_not_called()


def test_publish_failure_reports_redacted_diagnostics(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    synthetic_secret = "synthetic-google-api-token-for-test"
    monkeypatch.setattr(
        google_docs, "publish_markdown", Mock(side_effect=RuntimeError(synthetic_secret))
    )

    result = cli.main(["publish", "--config", str(config), "--publish", "review-pack-doc"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err.strip() == "publish failed: Google Docs API request was unsuccessful"
    assert synthetic_secret not in captured.err
    assert synthetic_secret not in captured.out
