from __future__ import annotations

import json
from pathlib import Path

from tests.adapter_contracts import assert_no_partial_adapter_artifacts
from tests.cli_helpers import run_cli
from tests.cli_output_assertions import (
    assert_contains_normalized,
    assert_write_summary,
    normalize_whitespace,
)


def test_confluence_cli_uses_installed_entrypoint_with_default_stub_client(
    tmp_path: Path,
) -> None:
    result = run_cli(
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
    assert "Wrote:" not in result.stdout
    assert_write_summary(result.stdout, wrote=1, skipped=0)
    assert "run_metrics:" in result.stdout
    assert "listing_requests: 0" in result.stdout
    assert "pages_discovered: 1" in result.stdout
    assert "page_fetch_requests: 1" in result.stdout
    assert "fetch_cache_hits: 0" in result.stdout
    assert "fetch_cache_misses: 0" in result.stdout
    assert "fetch_cache_saved_requests: 0" in result.stdout
    assert "request_summary:" not in result.stdout
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


def test_confluence_cli_rejects_invalid_request_delay(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
        "--request-delay-ms",
        "-1",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "argument --request-delay-ms: expected a non-negative integer." in result.stderr


def test_confluence_cli_rejects_invalid_max_requests_per_second(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        "./artifacts",
        "--max-requests-per-second",
        "0",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "argument --max-requests-per-second: expected a positive number." in result.stderr


def test_confluence_cli_tree_dry_run_with_stub_client_reports_discovery_limit(
    tmp_path: Path,
) -> None:
    result = run_cli(
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

    result = run_cli(
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


def test_confluence_cli_rejects_missing_tls_path_before_execution(
    tmp_path: Path,
) -> None:
    missing_ca_bundle = tmp_path / "missing-ca.pem"
    output_dir = tmp_path / "artifacts"

    result = run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "https://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        str(output_dir),
        "--ca-bundle",
        str(missing_ca_bundle),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "does not exist" in result.stderr
    assert str(missing_ca_bundle.resolve()) in result.stderr
    assert_no_partial_adapter_artifacts(output_dir)


def test_confluence_help_lists_supported_auth_methods_and_examples(
    tmp_path: Path,
) -> None:
    result = run_cli(
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
    assert "'real' fetches from Confluence" in stdout
    assert "--auth-method AUTH_METHOD" in stdout
    assert "--request-delay-ms MS" in stdout
    assert "--max-requests-per-second N" in stdout
    assert "the slower interval is used" in stdout
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
    output_dir = tmp_path / "artifacts"

    result = run_cli(
        tmp_path,
        "confluence",
        "--base-url",
        "ftp://example.com/wiki",
        "--target",
        "12345",
        "--output-dir",
        str(output_dir),
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
    assert_no_partial_adapter_artifacts(output_dir)
