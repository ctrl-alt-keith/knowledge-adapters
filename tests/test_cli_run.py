from __future__ import annotations

from pathlib import Path

from tests.cli_helpers import run_cli


def test_run_cli_executes_multiple_sources_from_yaml(tmp_path: Path) -> None:
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

    result = run_cli(tmp_path, "run", "./runs.yaml")

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


def test_run_cli_writes_markdown_report(tmp_path: Path) -> None:
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

    result = run_cli(tmp_path, "run", "./runs.yaml", "--report-output", "./reports/run.md")

    report_path = tmp_path / "reports" / "run.md"
    assert result.returncode == 0, result.stderr
    assert f"Run report: {report_path.resolve()}" in result.stdout
    report = report_path.read_text(encoding="utf-8")
    assert "# Knowledge Adapter Run Report" in report
    assert f"- Config: `{config_path.resolve()}`" in report
    assert "- Runs selected: 2" in report
    assert "- Runs completed: 2" in report
    assert "- Runs failed: 0" in report
    assert "| 1/2 | team-notes | local_files | completed | wrote 1, skipped 0 | - |" in report
    assert "| 2/2 | docs-home | confluence | completed | wrote 1, skipped 0 | - |" in report


def test_run_cli_report_includes_failure_classification(tmp_path: Path) -> None:
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

    result = run_cli(
        tmp_path,
        "run",
        "./runs.yaml",
        "--continue-on-error",
        "--report-output",
        "./reports/run.md",
    )

    report = (tmp_path / "reports" / "run.md").read_text(encoding="utf-8")
    assert result.returncode == 1
    assert "- Runs completed: 1" in report
    assert "- Runs failed: 1" in report
    assert "| 1/2 | docs-home | confluence | failed | " in report
    assert "| configuration |" in report
    assert "failure_class: configuration" in report
    assert "| 2/2 | team-notes | local_files | completed | wrote 1, skipped 0 | - |" in report


def test_run_cli_supports_only_and_disabled_runs(tmp_path: Path) -> None:
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

    result = run_cli(tmp_path, "run", "./runs.yaml", "--only", "docs-tree,docs-home")

    assert result.returncode == 0, result.stderr
    assert "only: docs-tree, docs-home" in result.stdout
    assert "runs_selected: 2" in result.stdout
    assert "runs_skipped_disabled: 0" in result.stdout
    assert "Run 1/2 started: docs-home (confluence)" in result.stdout
    assert "Run 2/2 started: docs-tree (confluence)" in result.stdout
    assert "Run 1/2 started: team-notes (local_files)" not in result.stdout
    assert not (tmp_path / "artifacts" / "local" / "team-notes" / "pages" / "today.md").exists()


def test_run_cli_rejects_unknown_only_name(tmp_path: Path) -> None:
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

    result = run_cli(tmp_path, "run", "./runs.yaml", "--only", "missing-run")

    assert result.returncode == 2
    assert result.stdout == ""
    assert (
        "knowledge-adapters run: error: Unknown run name(s) for --only in "
        f"{config_path.resolve()}: 'missing-run'. Available run names: 'team-notes'.\n"
    ) == result.stderr


def test_run_cli_rejects_invalid_confluence_config_before_execution(
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

    result = run_cli(tmp_path, "run", "./runs.yaml")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Config-driven run invoked" not in result.stdout
    assert "Run 1/1:" not in result.stdout
    assert (
        "knowledge-adapters run: error: Run 'docs-home' in "
        f"{config_path.resolve()} has unsupported 'client_mode' value 'preview'. "
        "Use 'real' or 'stub'.\n"
    ) == result.stderr


def test_run_cli_continue_on_error_executes_later_runs_and_returns_non_zero(
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

    result = run_cli(tmp_path, "run", "./runs.yaml", "--continue-on-error")

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


def test_run_cli_surfaces_stub_mode_warning_for_ignored_confluence_real_inputs(
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

    result = run_cli(tmp_path, "run", "./runs.yaml")

    assert result.returncode == 0, result.stderr
    assert (
        "warning: stub mode ignores real-mode Confluence inputs: --auth-method, "
        "--ca-bundle. Use --client-mode real to apply them."
    ) in result.stdout
