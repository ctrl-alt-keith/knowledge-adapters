from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.run_config import ConfiguredRun, load_run_config


def test_load_run_config_resolves_relative_paths_from_config_location(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.config_path == config_path.resolve()
    assert run_config.runs == (
        ConfiguredRun(
            name="docs-home",
            run_type="confluence",
            argv=(
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str((tmp_path / "artifacts" / "confluence" / "docs-home").resolve()),
            ),
            dry_run=False,
        ),
        ConfiguredRun(
            name="team-notes",
            run_type="local_files",
            argv=(
                "local_files",
                "--file-path",
                str((tmp_path / "inputs" / "team-notes.txt").resolve()),
                "--output-dir",
                str((tmp_path / "artifacts" / "local" / "team-notes").resolve()),
                "--dry-run",
            ),
            dry_run=True,
        ),
    )


def test_load_run_config_rejects_unsupported_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./notes.txt
    output_dir: ./artifacts
    unexpected: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported keys"):
        load_run_config(config_path)


@pytest.mark.parametrize(
    ("field_name", "field_block", "expected_fragment"),
    [
        (
            "client_mode",
            "client_mode: preview",
            "unsupported 'client_mode' value 'preview'",
        ),
        (
            "auth_method",
            "auth_method: oauth",
            "unsupported 'auth_method' value 'oauth'",
        ),
    ],
)
def test_load_run_config_rejects_invalid_confluence_enum_values(
    tmp_path: Path,
    field_name: str,
    field_block: str,
    expected_fragment: str,
) -> None:
    del field_name
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        f"""
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    {field_block}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=expected_fragment):
        load_run_config(config_path)


def test_load_run_config_rejects_invalid_confluence_target_before_execution(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: https://other.example.com/wiki/pages/viewpage.action?pageId=12345
    output_dir: ./artifacts/confluence/docs-home
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="has invalid 'target'"):
        load_run_config(config_path)


def test_load_run_config_rejects_negative_confluence_max_depth(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-tree
    tree: true
    max_depth: -1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="'max_depth'"):
        load_run_config(config_path)


def test_run_command_executes_multiple_runs_in_sequence(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: team-notes
    type: local_files
    file_path: ./inputs/team-notes.txt
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

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Config-driven run invoked" in captured.out
    assert "Run 1/2: team-notes (local_files)" in captured.out
    assert "Run 2/2: docs-home (confluence)" in captured.out
    assert captured.out.index("Run 1/2: team-notes (local_files)") < captured.out.index(
        "Run 2/2: docs-home (confluence)"
    )
    assert "Run summary: wrote 1, skipped 0" in captured.out
    assert "Aggregate summary:" in captured.out
    assert "runs_completed: 2" in captured.out
    assert "write_runs: 2" in captured.out
    assert "dry_run_runs: 0" in captured.out
    assert "wrote: 2" in captured.out
    assert "skipped: 0" in captured.out

    local_output_dir = tmp_path / "artifacts" / "local" / "team-notes"
    local_output_path = local_output_dir / "pages" / "team-notes.md"
    assert local_output_path.exists()
    assert "Ship it." in local_output_path.read_text(encoding="utf-8")
    local_manifest = json.loads((local_output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert local_manifest["files"] == [
        {
            "canonical_id": str(source_file.resolve()),
            "source_url": source_file.resolve().as_uri(),
            "output_path": "pages/team-notes.md",
            "title": "team-notes.txt",
        }
    ]

    confluence_output_dir = tmp_path / "artifacts" / "confluence" / "docs-home"
    confluence_output_path = confluence_output_dir / "pages" / "12345.md"
    assert confluence_output_path.exists()
    assert "Stub content for page 12345." in confluence_output_path.read_text(encoding="utf-8")
    confluence_manifest = json.loads(
        (confluence_output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert confluence_manifest["files"] == [
        {
            "canonical_id": "12345",
            "source_url": "https://example.com/wiki/pages/viewpage.action?pageId=12345",
            "output_path": "pages/12345.md",
            "title": "stub-page-12345",
            "page_version": 1,
            "last_modified": "1970-01-01T00:00:00Z",
        }
    ]


def test_run_command_reports_dry_run_counts(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-tree
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-tree
    tree: true
    max_depth: 1
    dry_run: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Run summary: would write 1, would skip 0" in captured.out
    assert "Aggregate summary:" in captured.out
    assert "write_runs: 0" in captured.out
    assert "dry_run_runs: 1" in captured.out
    assert "would_write: 1" in captured.out
    assert "would_skip: 0" in captured.out
    assert not (tmp_path / "artifacts").exists()


def test_run_command_preserves_nested_adapter_error_details(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CONFLUENCE_BEARER_TOKEN", raising=False)
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
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(config_path)])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Config-driven run invoked" in captured.out
    assert f"config_path: {config_path.resolve()}" in captured.out
    assert "runs_in_config: 1" in captured.out
    assert "Run 1/1: docs-home (confluence)" in captured.out
    assert (
        "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while "
        "executing knowledge-adapters confluence --base-url https://example.com/wiki "
        "--target 12345 --output-dir "
    ) in captured.err
    assert (
        "Missing Confluence bearer token. Set CONFLUENCE_BEARER_TOKEN for "
        "--client-mode real --auth-method bearer-env."
    ) in captured.err


def test_run_command_stops_on_first_failed_run_by_default(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CONFLUENCE_BEARER_TOKEN", raising=False)
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
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
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(config_path)])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Run 1/2: docs-home (confluence)" in captured.out
    assert "Run 2/2: team-notes (local_files)" not in captured.out
    assert "Aggregate summary:" not in captured.out
    assert "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while " in (
        captured.err
    )
    assert "Missing Confluence bearer token." in captured.err
    assert not (tmp_path / "artifacts" / "local" / "team-notes").exists()


def test_run_command_continue_on_error_executes_later_runs_and_reports_failures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CONFLUENCE_BEARER_TOKEN", raising=False)
    source_file = tmp_path / "inputs" / "team-notes.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("Ship it.\n", encoding="utf-8")
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
    file_path: ./inputs/team-notes.txt
    output_dir: ./artifacts/local/team-notes
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path), "--continue-on-error"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Run 1/2: docs-home (confluence)" in captured.out
    assert "Run 2/2: team-notes (local_files)" in captured.out
    assert "Aggregate summary:" in captured.out
    assert "runs_completed: 1" in captured.out
    assert "runs_failed: 1" in captured.out
    assert "write_runs: 1" in captured.out
    assert "dry_run_runs: 0" in captured.out
    assert "wrote: 1" in captured.out
    assert "skipped: 0" in captured.out
    assert "Config run completed with failures." in captured.out
    assert "knowledge-adapters run: error: Run 'docs-home' (confluence) failed while " in (
        captured.err
    )
    assert "Missing Confluence bearer token." in captured.err

    local_output_path = tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "team-notes.md"
    assert local_output_path.exists()
    assert "Ship it." in local_output_path.read_text(encoding="utf-8")


def test_load_run_config_includes_confluence_tls_and_client_cert_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/internal-ca.pem
    client_cert_file: ./certs/confluence-client.crt
    client_key_file: ./certs/confluence-client.key
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_config = load_run_config(config_path)

    assert run_config.runs == (
        ConfiguredRun(
            name="docs-home",
            run_type="confluence",
            argv=(
                "confluence",
                "--base-url",
                "https://example.com/wiki",
                "--target",
                "12345",
                "--output-dir",
                str((tmp_path / "artifacts" / "confluence" / "docs-home").resolve()),
                "--ca-bundle",
                str((tmp_path / "certs" / "internal-ca.pem").resolve()),
                "--client-cert-file",
                str((tmp_path / "certs" / "confluence-client.crt").resolve()),
                "--client-key-file",
                str((tmp_path / "certs" / "confluence-client.key").resolve()),
            ),
            dry_run=False,
        ),
    )


def test_load_run_config_rejects_confluence_client_key_without_client_cert(
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
    client_key_file: ./certs/confluence-client.key
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must set 'client_cert_file' when 'client_key_file'"):
        load_run_config(config_path)


def test_run_command_passes_confluence_tls_config_to_real_client(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from knowledge_adapters.confluence import client as client_module

    observed_kwargs: list[dict[str, object]] = []

    def stub_real_fetch(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        observed_kwargs.append(dict(kwargs))
        return {
            "canonical_id": "12345",
            "title": "Real Page",
            "content": "<p>Hello from Confluence.</p>",
            "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
            "page_version": 7,
            "last_modified": "2026-04-20T12:34:56Z",
        }

    monkeypatch.setattr(client_module, "fetch_real_page", stub_real_fetch, raising=False)
    config_path = tmp_path / "runs.yaml"
    config_path.write_text(
        """
runs:
  - name: docs-home
    type: confluence
    client_mode: real
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home
    ca_bundle: ./certs/internal-ca.pem
    client_cert_file: ./certs/confluence-client.crt
    client_key_file: ./certs/confluence-client.key
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(config_path)])

    assert exit_code == 0
    assert observed_kwargs == [
        {
            "base_url": "https://example.com/wiki",
            "auth_method": "bearer-env",
            "ca_bundle": str((tmp_path / "certs" / "internal-ca.pem").resolve()),
            "client_cert_file": str((tmp_path / "certs" / "confluence-client.crt").resolve()),
            "client_key_file": str((tmp_path / "certs" / "confluence-client.key").resolve()),
        }
    ]
