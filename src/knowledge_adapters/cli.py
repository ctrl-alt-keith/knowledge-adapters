"""CLI entrypoint for knowledge_adapters."""

from __future__ import annotations

import argparse
import io
import re
import shlex
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypedDict

from knowledge_adapters.bundle import (
    BUNDLE_ORDER_CHOICES,
    DEFAULT_BUNDLE_ORDER,
    DEFAULT_HEADER_MODE,
    HEADER_MODE_CHOICES,
    describe_bundle_order,
    describe_header_mode,
)
from knowledge_adapters.confluence.auth import SUPPORTED_AUTH_METHODS, resolve_tls_inputs

TOP_LEVEL_HELP_EXAMPLES = """First steps:
  knowledge-adapters --help
  knowledge-adapters run runs.yaml
  knowledge-adapters local_files --help
  knowledge-adapters git_repo --help
  knowledge-adapters github_metadata --help
  knowledge-adapters confluence --help
  knowledge-adapters bundle ./artifacts --output ./bundle.md

Typical flow:
  1. Start with local_files to try the artifact layout with a text file you
     already have.
  2. Start with --dry-run to preview the source, artifact path, manifest path,
     and action.
  3. Re-run without --dry-run to write the same artifact layout under
     ./artifacts.
  4. Use knowledge-adapters run runs.yaml to refresh multiple sources in order.
  5. Use knowledge-adapters bundle ./artifacts --output ./bundle.md to combine
     generated artifacts into one prompt-ready markdown file.
"""

CONFLUENCE_HELP_EXAMPLES = """Examples:
  knowledge-adapters confluence \\
    --base-url https://example.com/wiki \\
    --target 12345 \\
    --output-dir ./artifacts \\
    --dry-run
  knowledge-adapters confluence \\
    --base-url https://example.com/wiki \\
    --target 12345 \\
    --output-dir ./artifacts \\
    --tree \\
    --max-depth 1 \\
    --dry-run
  knowledge-adapters confluence \\
    --base-url https://example.com/wiki \\
    --target 12345 \\
    --output-dir ./artifacts
  CONFLUENCE_BEARER_TOKEN=... knowledge-adapters confluence \\
    --client-mode real \\
    --auth-method bearer-env \\
    --base-url https://example.com/wiki \\
    --target 12345 \\
    --output-dir ./artifacts
"""

LOCAL_FILES_HELP_EXAMPLES = """Examples:
  knowledge-adapters local_files \\
    --file-path ./notes/today.txt \\
    --output-dir ./artifacts \\
    --dry-run
  knowledge-adapters local_files \\
    --file-path ./notes/today.txt \\
    --output-dir ./artifacts
"""

GIT_REPO_HELP_EXAMPLES = """Examples:
  knowledge-adapters git_repo \\
    --repo-url https://github.com/example/project.git \\
    --output-dir ./artifacts \\
    --dry-run
  knowledge-adapters git_repo \\
    --repo-url https://github.com/example/project.git \\
    --ref v1.2.3 \\
    --include \"docs/**/*.md\" \\
    --exclude \"docs/archive/*\" \\
    --output-dir ./artifacts
  knowledge-adapters git_repo \\
    --repo-url https://github.com/example/project.git \\
    --subdir docs \\
    --output-dir ./artifacts
"""

GITHUB_METADATA_HELP_EXAMPLES = """Examples:
  GITHUB_TOKEN=... knowledge-adapters github_metadata \\
    --repo example/project \\
    --token-env GITHUB_TOKEN \\
    --output-dir ./artifacts \\
    --dry-run
  GITHUB_TOKEN=... knowledge-adapters github_metadata \\
    --repo example/project \\
    --token-env GITHUB_TOKEN \\
    --resource-type pull_request \\
    --output-dir ./artifacts \\
    --dry-run
  GITHUB_TOKEN=... knowledge-adapters github_metadata \\
    --repo example/project \\
    --token-env GITHUB_TOKEN \\
    --state all \\
    --since 2026-01-01T00:00:00Z \\
    --max-items 25 \\
    --output-dir ./artifacts
  GHE_TOKEN=... knowledge-adapters github_metadata \\
    --repo example/project \\
    --base-url https://github.example.com \\
    --token-env GHE_TOKEN \\
    --output-dir ./artifacts
"""

RUN_HELP_EXAMPLES = """Examples:
  knowledge-adapters run runs.yaml
  knowledge-adapters run ./configs/runs.yaml
  knowledge-adapters run runs.yaml --only team-notes,docs-home
  knowledge-adapters run runs.yaml --continue-on-error
"""

BUNDLE_HELP_EXAMPLES = """Examples:
  knowledge-adapters bundle ./artifacts/confluence --output ./bundle.md
  knowledge-adapters bundle ./artifacts/a ./artifacts/b --output ./bundle.md
  knowledge-adapters bundle ./artifacts/manifest.json --output ./bundle.md
  knowledge-adapters bundle ./artifacts --header-mode minimal --output ./bundle.md
  knowledge-adapters bundle ./artifacts --include "team-*" --exclude "*draft*" --output ./bundle.md
  knowledge-adapters bundle ./artifacts --max-bytes 250000 --output ./bundle.md
  knowledge-adapters bundle ./artifacts --changed-only \\
    --baseline-manifest ./prior/manifest.json --output ./bundle.md
"""

_WRITE_SUMMARY_RE = re.compile(r"Summary: wrote (?P<wrote>\d+), skipped (?P<skipped>\d+)")
_DRY_RUN_SUMMARY_RE = re.compile(
    r"Summary: would write (?P<wrote>\d+), would skip (?P<skipped>\d+)"
)
_DRY_RUN_BLOCK_WRITE_RE = re.compile(r"would_write: (?P<wrote>\d+)")
_DRY_RUN_BLOCK_SKIP_RE = re.compile(r"would_skip: (?P<skipped>\d+)")
_CLI_ERROR_RE = re.compile(r"^knowledge-adapters (?P<command>\S+): error: (?P<message>.+)$")
_CONFLUENCE_REAL_ONLY_INPUT_FLAGS = (
    "--auth-method",
    "--ca-bundle",
    "--no-ca-bundle",
    "--client-cert-file",
    "--client-key-file",
)


@dataclass(frozen=True)
class MultiRunSummary:
    """Summary parsed from one adapter CLI execution."""

    dry_run: bool
    wrote: int
    skipped: int


class RealClientTLSKwargs(TypedDict, total=False):
    """Keyword arguments shared by Confluence real-client calls."""

    ca_bundle: str | None
    no_ca_bundle: bool
    client_cert_file: str | None
    client_key_file: str | None


class _TeeStream:
    """Write nested CLI stdout both live and into an in-memory buffer."""

    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _parse_confluence_auth_method(value: str) -> str:
    """Parse and validate a supported Confluence auth method."""
    normalized_value = value.strip()
    if normalized_value in SUPPORTED_AUTH_METHODS:
        return normalized_value

    supported_values = " or ".join(repr(method) for method in SUPPORTED_AUTH_METHODS)
    raise argparse.ArgumentTypeError(f"unsupported value {value!r}. Choose {supported_values}.")


def _parse_only_run_names(value: str) -> tuple[str, ...]:
    """Parse a comma-separated run selection list."""
    parsed_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in value.split(","):
        name = raw_name.strip()
        if not name or name in seen_names:
            continue
        parsed_names.append(name)
        seen_names.add(name)

    if not parsed_names:
        raise argparse.ArgumentTypeError("expected one or more comma-separated run names.")

    return tuple(parsed_names)


def _parse_positive_int(value: str) -> int:
    """Parse a strictly positive integer CLI value."""
    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer.") from exc

    if parsed_value < 1:
        raise argparse.ArgumentTypeError("expected a positive integer.")

    return parsed_value


def exit_with_output_error(
    output_dir: str | Path,
    *,
    command: str,
    exc: OSError,
) -> None:
    """Exit with a consistent filesystem error for output writes."""
    resolved_output_dir = Path(output_dir).expanduser()
    if isinstance(exc, PermissionError):
        exit_with_cli_error(
            (
                f"Output directory is not writable: {resolved_output_dir}. "
                "Verify --output-dir and check the path permissions."
            ),
            command=command,
        )
    if isinstance(exc, NotADirectoryError):
        exit_with_cli_error(
            (
                f"Output path is not a directory: {resolved_output_dir}. "
                "Verify --output-dir and use a directory path."
            ),
            command=command,
        )

    exit_with_cli_error(
        (f"Could not write output under {resolved_output_dir}. Verify --output-dir and try again."),
        command=command,
    )


def exit_with_bundle_output_error(output_path: str | Path, *, exc: OSError) -> None:
    """Exit with a consistent filesystem error for bundle output writes."""
    resolved_output_path = Path(output_path).expanduser()
    if isinstance(exc, PermissionError):
        exit_with_cli_error(
            (
                f"Bundle output is not writable: {resolved_output_path}. "
                "Verify --output and check the path permissions."
            ),
            command="bundle",
        )
    if isinstance(exc, IsADirectoryError):
        exit_with_cli_error(
            (
                f"Bundle output path is a directory: {resolved_output_path}. "
                "Verify --output and use a file path."
            ),
            command="bundle",
        )
    if isinstance(exc, NotADirectoryError):
        exit_with_cli_error(
            (
                f"Bundle output path is invalid: {resolved_output_path}. "
                "Verify --output and use a file path."
            ),
            command="bundle",
        )

    exit_with_cli_error(
        (f"Could not write bundle output {resolved_output_path}. Verify --output and try again."),
        command="bundle",
    )


def exit_with_local_files_artifact_collision(
    *,
    output_path: Path,
    manifest_output_path: Path,
    prior_source_path: str,
    current_source_path: str,
) -> None:
    """Exit with a consistent artifact-collision error for local_files."""
    exit_with_cli_error(
        (
            f"Artifact path collision: {output_path} is already mapped to source file "
            f"{prior_source_path} in {manifest_output_path}, but this run resolves "
            f"{current_source_path}. Remove or rename one of the source files, or clear "
            "the stale artifact directory before retrying."
        ),
        command="local_files",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="knowledge-adapters",
        description=(
            "Normalize knowledge sources into a shared local artifact layout. "
            "Every run inspects a source, plans a markdown artifact under pages/ "
            "plus manifest.json, and writes only when --dry-run is not set."
        ),
        epilog=TOP_LEVEL_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    confluence_parser = subparsers.add_parser(
        "confluence",
        help=(
            "Normalize Confluence content into shared artifacts. "
            "Start with one page or use --tree to include descendants."
        ),
        description=(
            "Normalize a Confluence page or, with --tree, a page tree into the "
            "shared artifact layout. Start with one page, then add --tree when "
            "you want descendants. Stub and real modes keep the same resolve, "
            "plan, and write flow. Use --dry-run to preview resolved page IDs, "
            "planned artifact paths, manifest path, and write/skip decisions "
            "before writing. In tree mode, dry-run previews the root page and "
            "discovered descendants included by --max-depth and the artifact "
            "paths used in write mode. Use "
            "--max-depth to limit descendant levels. Ignored unless --tree is "
            "set. The default stub mode uses scaffolded content "
            "without contacting Confluence. Use --client-mode real for "
            "contract-tested live fetches."
        ),
        epilog=CONFLUENCE_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    confluence_parser.add_argument(
        "--base-url",
        required=True,
        help=(
            "Base Confluence URL for validating full page URLs and building canonical source URLs."
        ),
    )
    confluence_parser.add_argument(
        "--target",
        help=(
            "Confluence page ID or full page URL under --base-url. The CLI resolves "
            "either input into one canonical page ID and source URL for artifact "
            "and manifest reporting."
        ),
    )
    confluence_parser.add_argument(
        "--space-key",
        help=("Confluence space key for bounded real-mode discovery of all pages in one space."),
    )
    confluence_parser.add_argument(
        "--space-url",
        help=(
            "Full Confluence space overview URL matching /spaces/{SPACE}/overview "
            "for bounded real-mode discovery of all pages in one space."
        ),
    )
    confluence_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where pages/ and manifest.json are written.",
    )
    confluence_parser.add_argument(
        "--ca-bundle",
        metavar="FILE",
        help=(
            "PEM bundle to trust for TLS verification in --client-mode real. "
            "When set, this overrides default certificate discovery for "
            "Confluence HTTPS requests."
        ),
    )
    confluence_parser.add_argument(
        "--no-ca-bundle",
        action="store_true",
        help=(
            "Disable Confluence CA bundle usage for this run, overriding "
            "--ca-bundle and KNOWLEDGE_ADAPTERS_CONFLUENCE_CA_BUNDLE."
        ),
    )
    confluence_parser.add_argument(
        "--client-cert-file",
        help=argparse.SUPPRESS,
    )
    confluence_parser.add_argument(
        "--client-key-file",
        help=argparse.SUPPRESS,
    )
    confluence_parser.add_argument(
        "--client-mode",
        choices=("stub", "real"),
        default="stub",
        help=(
            "Choose the content source: 'stub' uses scaffolded page content with no "
            "network call; 'real' fetches from Confluence using --auth-method. Both "
            "modes keep the same artifact layout and reporting. Defaults to 'stub'."
        ),
    )
    confluence_parser.add_argument(
        "--auth-method",
        type=_parse_confluence_auth_method,
        default="bearer-env",
        metavar="AUTH_METHOD",
        help=(
            "Auth for --client-mode real: 'bearer-env' reads "
            "CONFLUENCE_BEARER_TOKEN; 'client-cert-env' reads "
            "CONFLUENCE_CLIENT_CERT_FILE and optional "
            "CONFLUENCE_CLIENT_KEY_FILE. Defaults to 'bearer-env'."
        ),
    )
    confluence_parser.add_argument(
        "--debug",
        action="store_true",
        help="Show Confluence request debug details for real-client failures.",
    )
    confluence_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview resolved page IDs, artifact paths, manifest path, and "
            "write/skip decisions without writing files."
        ),
    )
    confluence_parser.add_argument(
        "--tree",
        action="store_true",
        help=(
            "Traverse the resolved root page and discovered descendants "
            "instead of only one page. Use --max-depth to limit descendant "
            "levels."
        ),
    )
    confluence_parser.add_argument(
        "--max-depth",
        type=int,
        default=0,
        help=(
            "Maximum descendant depth for --tree. 0 keeps only the root page; "
            "1 adds direct children.\n\nIgnored unless --tree is set."
        ),
    )

    local_files_parser = subparsers.add_parser(
        "local_files",
        help="Normalize one local UTF-8 text file into shared artifacts.",
        description=(
            "Normalize one existing UTF-8 text file into the shared artifact layout. "
            "Start with --dry-run to preview the resolved file path, artifact path, "
            "manifest path, and normalized markdown before writing. Empty UTF-8 "
            "files are allowed and produce an empty content section. Files that "
            "are not valid UTF-8 text are rejected, and directories are not "
            "supported. Unlike "
            "Confluence, local_files handles one file per run and always plans one write; "
            "it does not use manifest-based skip logic."
        ),
        epilog=LOCAL_FILES_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    local_files_parser.add_argument(
        "--file-path",
        required=True,
        metavar="FILE",
        help=(
            "Path to the one existing local UTF-8 text file for this run. Empty "
            "files are allowed; directories are not supported. Relative paths "
            "resolve from the cwd."
        ),
    )
    local_files_parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="Directory where pages/ and manifest.json are written.",
    )
    local_files_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview the resolved file path, artifact path, manifest path, and "
            "normalized markdown without writing files."
        ),
    )

    git_repo_parser = subparsers.add_parser(
        "git_repo",
        help="Normalize selected UTF-8 text files from a Git repository into shared artifacts.",
        description=(
            "Clone or refresh a Git repository with system git, check out the selected "
            "ref or the repository default branch, enumerate tracked files, apply optional "
            "include/exclude glob filters, and normalize one artifact per UTF-8 text file "
            "into the shared artifact layout. An optional --subdir limits enumeration to "
            "one repository-relative directory. Binary and non-UTF-8 files are skipped "
            "with explicit reporting. File ordering is deterministic and lexical by "
            "repository path."
        ),
        epilog=GIT_REPO_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    git_repo_parser.add_argument(
        "--repo-url",
        required=True,
        help=(
            "Git repository URL or other git clone locator. Relative local paths resolve "
            "from the cwd."
        ),
    )
    git_repo_parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="Directory where pages/ and manifest.json are written.",
    )
    git_repo_parser.add_argument(
        "--ref",
        help="Branch, tag, or commit to check out. Defaults to the repository default branch.",
    )
    git_repo_parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Glob pattern matched against repository-relative file paths. Repeat to include "
            "multiple patterns. If omitted, all tracked files start included."
        ),
    )
    git_repo_parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Glob pattern matched against repository-relative file paths after include "
            "filtering. Repeat to exclude multiple patterns."
        ),
    )
    git_repo_parser.add_argument(
        "--subdir",
        help="Optional repository-relative directory to enumerate instead of the whole checkout.",
    )
    git_repo_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview the resolved ref, commit SHA, selected files, artifact paths, and "
            "skip reasons without writing files."
        ),
    )

    github_metadata_parser = subparsers.add_parser(
        "github_metadata",
        help=(
            "Normalize GitHub issue or pull request metadata from one repository into "
            "shared artifacts."
        ),
        description=(
            "Fetch issues or pull requests from one GitHub or GitHub Enterprise "
            "repository through the REST API and normalize one markdown artifact per "
            "record under issues/ or pull_requests/. Issue mode filters out pull "
            "requests returned by the issues endpoint. Issue comments can be included "
            "optionally in issue mode. Pull request comments, releases, timelines, "
            "reactions, reviews, checks, GraphQL, attachments, and live sync are not "
            "included. The token is read only from --token-env, and token values are "
            "never printed."
        ),
        epilog=GITHUB_METADATA_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    github_metadata_parser.add_argument(
        "--repo",
        required=True,
        metavar="OWNER/NAME",
        help="Repository to read, in owner/name form.",
    )
    github_metadata_parser.add_argument(
        "--base-url",
        help=(
            "GitHub Enterprise web root or API root ending in /api/v3. Defaults to "
            "GitHub.com, using https://github.com for source URLs and "
            "https://api.github.com for REST API requests."
        ),
    )
    github_metadata_parser.add_argument(
        "--token-env",
        required=True,
        metavar="ENV_VAR",
        help=(
            "Name of the environment variable containing the GitHub token. The token "
            "value is read from the environment only and is never printed."
        ),
    )
    github_metadata_parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="Directory where issues/ or pull_requests/ plus manifest.json are written.",
    )
    github_metadata_parser.add_argument(
        "--resource-type",
        choices=("issue", "pull_request"),
        default="issue",
        help="GitHub metadata resource type to ingest. Defaults to issue.",
    )
    github_metadata_parser.add_argument(
        "--state",
        choices=("open", "closed", "all"),
        default="open",
        help="Issue state filter for the REST API. Defaults to open.",
    )
    github_metadata_parser.add_argument(
        "--since",
        help="ISO 8601 timestamp for issues updated at or after that time.",
    )
    github_metadata_parser.add_argument(
        "--max-items",
        type=_parse_positive_int,
        metavar="N",
        help="Positive issue limit applied after filtering out pull requests.",
    )
    github_metadata_parser.add_argument(
        "--include-issue-comments",
        action="store_true",
        help=(
            "Fetch issue comments and append them to issue artifacts. Ignored for "
            "pull_request resource type."
        ),
    )
    github_metadata_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetch and plan matching issues without creating directories, writing "
            "issue artifacts, or writing manifest.json."
        ),
    )

    bundle_parser = subparsers.add_parser(
        "bundle",
        help="Combine existing artifacts into one prompt-ready markdown file.",
        description=(
            "Combine existing artifacts into one prompt-ready markdown file. Accept one "
            "or more output directories or manifest files as input. Bundle output keeps "
            "the original artifacts unchanged, removes duplicate canonical_id entries by "
            "keeping the first artifact discovered from the provided inputs, and orders "
            "the final sections using the selected deterministic ordering mode. Header "
            "modes control how much manifest metadata appears above each document. Optional "
            "glob-style include and exclude filters match canonical_id, title, "
            "output_path, and source_url. If no --include filters are provided, all "
            "artifacts start included. Exclude filters apply after include matching and "
            "win on conflicts. With --changed-only, a baseline manifest is used to keep "
            "only artifacts with new canonical_id values or changed content_hash values. "
            "With --max-bytes, bundle output is split into deterministic numbered "
            "markdown files and sections are kept intact when possible."
        ),
        epilog=BUNDLE_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bundle_parser.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help="One or more adapter output directories or manifest files to bundle.",
    )
    bundle_parser.add_argument(
        "--output",
        required=True,
        metavar="FILE",
        help="Markdown file to write with the bundled artifact content.",
    )
    bundle_parser.add_argument(
        "--max-bytes",
        type=_parse_positive_int,
        metavar="N",
        help=(
            "Split bundle output into numbered markdown files when possible, each at "
            "or below N UTF-8 bytes. Splits happen only between artifact sections; a "
            "single oversized artifact is written to its own file and reported."
        ),
    )
    bundle_parser.add_argument(
        "--order",
        choices=BUNDLE_ORDER_CHOICES,
        default=DEFAULT_BUNDLE_ORDER,
        help=(
            "Deterministic output ordering: canonical_id sorts lexically by canonical_id "
            "(default); manifest preserves manifest entry order; input preserves bundle "
            "input order, then manifest order within each input."
        ),
    )
    bundle_parser.add_argument(
        "--header-mode",
        choices=HEADER_MODE_CHOICES,
        default=DEFAULT_HEADER_MODE,
        help=(
            "Per-document header detail: full includes source_url, canonical_id, and "
            "optional fetched_at, path, and ref metadata when present (default); "
            "minimal includes only the title and source_url."
        ),
    )
    bundle_parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Repeatable glob-style filter. When provided, keep only artifacts matching "
            "at least one pattern across canonical_id, title, output_path, or source_url."
        ),
    )
    bundle_parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Repeatable glob-style filter applied after --include matching across "
            "canonical_id, title, output_path, or source_url. Exclude wins on conflicts."
        ),
    )
    bundle_parser.add_argument(
        "--changed-only",
        action="store_true",
        help=(
            "Keep only artifacts that are new or changed compared with "
            "--baseline-manifest. Requires --baseline-manifest."
        ),
    )
    bundle_parser.add_argument(
        "--baseline-manifest",
        metavar="PATH",
        help=(
            "Prior manifest.json to compare by canonical_id and content_hash when "
            "--changed-only is set."
        ),
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Execute multiple configured adapter runs from one YAML file.",
        description=(
            "Load a YAML config with a top-level runs: list and execute each "
            "configured adapter run sequentially in file order. Each run reuses "
            "the existing adapter CLI behavior, output directory, and manifest "
            "handling."
        ),
        epilog=RUN_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_parser.add_argument(
        "config_path",
        metavar="RUNS_YAML",
        help="Path to a YAML config file containing a top-level runs: list.",
    )
    run_parser.add_argument(
        "--only",
        type=_parse_only_run_names,
        metavar="RUN_NAMES",
        help=(
            "Run only the named config entries from runs.yaml, matched by run name "
            "and still executed in config order. Explicit selection overrides "
            "enabled: false for those named runs."
        ),
    )
    run_parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help=(
            "Keep executing later configured runs after one run fails. "
            "Returns non-zero if any configured run fails."
        ),
    )
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Append --debug to configured Confluence runs so nested request "
            "details and effective TLS inputs are surfaced without editing runs.yaml."
        ),
    )
    run_parser.add_argument(
        "--no-ca-bundle",
        action="store_true",
        help=(
            "Append --no-ca-bundle to configured Confluence runs so CA bundle "
            "usage can be disabled without editing runs.yaml."
        ),
    )

    return parser


def print_cli_error(
    message: str,
    *,
    command: str,
    debug_lines: Sequence[str] | None = None,
) -> None:
    """Print a stable user-facing CLI error message."""
    print(f"knowledge-adapters {command}: error: {message}", file=sys.stderr)
    if debug_lines:
        for line in debug_lines:
            print(f"  {line}", file=sys.stderr)


def exit_with_cli_error(
    message: str,
    *,
    command: str,
    debug_lines: Sequence[str] | None = None,
) -> None:
    """Exit the CLI with a stable user-facing error message."""
    print_cli_error(message, command=command, debug_lines=debug_lines)
    raise SystemExit(2)


def render_user_path(path: str | Path) -> str:
    """Render user-facing paths with one consistent absolute form."""
    return str(Path(path).expanduser().resolve())


def print_stale_artifacts(
    output_dir: str | Path,
    stale_artifacts: Sequence[tuple[str, str]],
) -> None:
    """Print a preview of stale artifacts that remain on disk."""
    if not stale_artifacts:
        return

    stale_preview_limit = 5
    output_dir_path = Path(output_dir)
    print("  Stale artifacts:")
    for canonical_id, relative_output_path in stale_artifacts[:stale_preview_limit]:
        print(
            "    "
            f"{render_user_path(output_dir_path / relative_output_path)} "
            f"(canonical_id: {canonical_id})"
        )
    remaining_count = len(stale_artifacts) - stale_preview_limit
    if remaining_count > 0:
        print(f"    ... and {remaining_count} more")


def print_dry_run_complete() -> None:
    """Print a consistent dry-run completion message."""
    print("\nDry run complete. No files written.")


def print_write_complete(output_dir: Path) -> None:
    """Print a consistent write completion message."""
    print(f"\nWrite complete. Artifacts created under {render_user_path(output_dir)}")


def _parse_multi_run_summary(output: str) -> MultiRunSummary:
    """Parse the existing adapter summary lines into one normalized shape."""
    if match := _WRITE_SUMMARY_RE.search(output):
        return MultiRunSummary(
            dry_run=False,
            wrote=int(match.group("wrote")),
            skipped=int(match.group("skipped")),
        )

    if match := _DRY_RUN_SUMMARY_RE.search(output):
        return MultiRunSummary(
            dry_run=True,
            wrote=int(match.group("wrote")),
            skipped=int(match.group("skipped")),
        )

    dry_run_write_match = _DRY_RUN_BLOCK_WRITE_RE.search(output)
    dry_run_skip_match = _DRY_RUN_BLOCK_SKIP_RE.search(output)
    if dry_run_write_match and dry_run_skip_match:
        return MultiRunSummary(
            dry_run=True,
            wrote=int(dry_run_write_match.group("wrote")),
            skipped=int(dry_run_skip_match.group("skipped")),
        )

    raise RuntimeError(f"Could not parse adapter summary from output:\n{output}")


def _parse_nested_cli_error(stderr_output: str) -> tuple[str | None, tuple[str, ...]]:
    """Extract the actionable message from a nested CLI failure."""
    lines = tuple(line for line in stderr_output.splitlines() if line.strip())
    if not lines:
        return None, ()

    for index, line in enumerate(lines):
        match = _CLI_ERROR_RE.match(line)
        if match is not None:
            return match.group("message"), lines[index + 1 :]

    return lines[-1], ()


def _build_configured_run_failure(
    *,
    configured_run_name: str,
    configured_run_type: str,
    display_command: str,
    stderr_output: str,
    exit_code: int | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Build one stable configured-run failure message."""
    nested_error, nested_details = _parse_nested_cli_error(stderr_output)
    if exit_code is None:
        message = (
            f"Run {configured_run_name!r} ({configured_run_type}) failed while "
            f"executing {display_command}."
        )
    else:
        message = (
            f"Run {configured_run_name!r} ({configured_run_type}) returned "
            f"exit code {exit_code} while executing {display_command}."
        )
    if nested_error is not None:
        message = f"{message} {nested_error}"
    return message, nested_details


def _effective_configured_run_argv(
    *,
    run_type: str,
    argv: Sequence[str],
    debug: bool,
) -> tuple[str, ...]:
    """Apply safe top-level run overrides before invoking a configured run."""
    effective_argv = tuple(argv)
    if not debug or run_type != "confluence" or "--debug" in effective_argv:
        return effective_argv
    return (*effective_argv, "--debug")


def _execute_configured_run(
    argv: Sequence[str],
    *,
    captured_stdout: TextIO,
    captured_stderr: TextIO,
) -> int:
    """Execute one configured run while teeing nested stdout into the parent CLI."""
    with redirect_stdout(_TeeStream(sys.stdout, captured_stdout)), redirect_stderr(captured_stderr):
        return main(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    raw_argv = tuple(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(raw_argv)

    if args.command == "run":
        from knowledge_adapters.run_config import load_run_config, select_runs

        try:
            run_config = load_run_config(
                args.config_path,
                no_confluence_ca_bundle=args.no_ca_bundle,
            )
            selected_runs = select_runs(run_config, only_names=args.only)
        except ValueError as exc:
            exit_with_cli_error(str(exc), command="run")

        skipped_disabled_runs = (
            ()
            if args.only is not None
            else tuple(
                configured_run for configured_run in run_config.runs if not configured_run.enabled
            )
        )

        print("Config-driven run invoked")
        print(f"  config_path: {render_user_path(run_config.config_path)}")
        print(f"  runs_in_config: {len(run_config.runs)}")
        if args.only is not None:
            print(f"  only: {', '.join(args.only)}")
            print(f"  runs_selected: {len(selected_runs)}")
        if skipped_disabled_runs:
            print(f"  runs_skipped_disabled: {len(skipped_disabled_runs)}")
            for configured_run in skipped_disabled_runs:
                print(f"  skipped_disabled: {configured_run.name} ({configured_run.run_type})")

        completed_runs = 0
        failed_runs = 0
        interrupted_runs = 0
        write_runs = 0
        dry_run_runs = 0
        total_wrote = 0
        total_skipped = 0
        total_would_write = 0
        total_would_skip = 0
        interrupt_requested = False

        for index, configured_run in enumerate(selected_runs, start=1):
            effective_argv = _effective_configured_run_argv(
                run_type=configured_run.run_type,
                argv=configured_run.argv,
                debug=args.debug,
            )
            display_command = shlex.join(("knowledge-adapters", *effective_argv))
            print(
                f"\nRun {index}/{len(selected_runs)} started: "
                f"{configured_run.name} ({configured_run.run_type})"
            )
            print(f"  command: {display_command}")

            captured_stdout = io.StringIO()
            captured_stderr = io.StringIO()
            try:
                exit_code = _execute_configured_run(
                    effective_argv,
                    captured_stdout=captured_stdout,
                    captured_stderr=captured_stderr,
                )
            except KeyboardInterrupt:
                if interrupt_requested:
                    raise

                interrupt_requested = True
                interrupted_runs += 1
                print(
                    f"Run {index}/{len(selected_runs)} interrupted: "
                    f"{configured_run.name} ({configured_run.run_type})"
                )
                print("Run interrupted: skipping remaining work for this run")
                print("Run summary: interrupted, skipped remaining work for this run")
                continue
            except SystemExit:
                print(
                    f"Run {index}/{len(selected_runs)} failed: "
                    f"{configured_run.name} ({configured_run.run_type})"
                )
                message, nested_details = _build_configured_run_failure(
                    configured_run_name=configured_run.name,
                    configured_run_type=configured_run.run_type,
                    display_command=display_command,
                    stderr_output=captured_stderr.getvalue(),
                )
                if not args.continue_on_error:
                    exit_with_cli_error(
                        message,
                        command="run",
                        debug_lines=nested_details or None,
                    )
                print_cli_error(message, command="run", debug_lines=nested_details or None)
                failed_runs += 1
                continue

            if exit_code != 0:
                print(
                    f"Run {index}/{len(selected_runs)} failed: "
                    f"{configured_run.name} ({configured_run.run_type})"
                )
                message, nested_details = _build_configured_run_failure(
                    configured_run_name=configured_run.name,
                    configured_run_type=configured_run.run_type,
                    display_command=display_command,
                    stderr_output=captured_stderr.getvalue(),
                    exit_code=exit_code,
                )
                if not args.continue_on_error:
                    exit_with_cli_error(
                        message,
                        command="run",
                        debug_lines=nested_details or None,
                    )
                print_cli_error(message, command="run", debug_lines=nested_details or None)
                failed_runs += 1
                continue

            output = captured_stdout.getvalue()

            try:
                summary = _parse_multi_run_summary(output)
            except RuntimeError as exc:
                exit_with_cli_error(str(exc), command="run")

            print(
                f"Run {index}/{len(selected_runs)} completed: "
                f"{configured_run.name} ({configured_run.run_type})"
            )
            completed_runs += 1
            if summary.dry_run:
                dry_run_runs += 1
                total_would_write += summary.wrote
                total_would_skip += summary.skipped
                print(f"Run summary: would write {summary.wrote}, would skip {summary.skipped}")
            else:
                write_runs += 1
                total_wrote += summary.wrote
                total_skipped += summary.skipped
                print(f"Run summary: wrote {summary.wrote}, skipped {summary.skipped}")

        print("\nAggregate summary:")
        print(f"  runs_completed: {completed_runs}")
        print(f"  runs_failed: {failed_runs}")
        print(f"  runs_interrupted: {interrupted_runs}")
        print(f"  runs_skipped_disabled: {len(skipped_disabled_runs)}")
        print(f"  write_runs: {write_runs}")
        print(f"  dry_run_runs: {dry_run_runs}")
        print(f"  wrote: {total_wrote}")
        print(f"  skipped: {total_skipped}")
        if dry_run_runs > 0:
            print(f"  would_write: {total_would_write}")
            print(f"  would_skip: {total_would_skip}")
        if failed_runs > 0:
            if interrupted_runs > 0:
                print(
                    "Config run completed with failures. "
                    f"Processed {completed_runs} successful run(s), {failed_runs} failed "
                    f"run(s), and {interrupted_runs} interrupted run(s) from "
                    f"{render_user_path(run_config.config_path)}"
                )
            else:
                print(
                    "Config run completed with failures. "
                    f"Processed {completed_runs} successful run(s) and {failed_runs} failed "
                    f"run(s) from {render_user_path(run_config.config_path)}"
                )
            return 1

        if interrupted_runs > 0:
            print(
                "Config run complete. "
                f"Processed {completed_runs} completed run(s) and {interrupted_runs} "
                f"interrupted run(s) from {render_user_path(run_config.config_path)}"
            )
        else:
            print(
                "Config run complete. "
                f"Processed {completed_runs} run(s) from {render_user_path(run_config.config_path)}"
            )
        return 0

    if args.command == "confluence":
        from knowledge_adapters.confluence.client import (
            ConfluenceRequestError,
            fetch_page,
            fetch_real_page,
            fetch_real_page_summary,
            list_real_child_page_ids,
            list_real_space_page_ids,
        )
        from knowledge_adapters.confluence.config import (
            ConfluenceConfig,
            validate_explicit_tls_paths,
            validate_selected_real_tls_paths,
        )
        from knowledge_adapters.confluence.incremental import (
            PageSyncDecision,
            classify_page_sync,
        )
        from knowledge_adapters.confluence.models import ResolvedTarget
        from knowledge_adapters.confluence.normalize import normalize_to_markdown
        from knowledge_adapters.confluence.resolve import (
            resolve_target_for_base_url,
            space_key_from_url_for_base_url,
            validate_space_key,
        )
        from knowledge_adapters.confluence.traversal import TreeWalkProgress, walk_pages
        from knowledge_adapters.confluence.writer import markdown_path, write_markdown
        from knowledge_adapters.manifest import (
            build_manifest_entry,
            manifest_path,
            write_manifest,
            write_manifest_with_context,
        )
        from knowledge_adapters.manifest_stale import (
            find_stale_artifacts,
            load_previous_manifest_index,
        )

        confluence_config = ConfluenceConfig(
            base_url=args.base_url,
            target=args.target,
            output_dir=args.output_dir,
            space_key=args.space_key,
            space_url=args.space_url,
            ca_bundle=args.ca_bundle,
            no_ca_bundle=args.no_ca_bundle,
            client_cert_file=args.client_cert_file,
            client_key_file=args.client_key_file,
            client_mode=args.client_mode,
            auth_method=args.auth_method,
            debug=args.debug,
            dry_run=args.dry_run,
            tree=args.tree,
            max_depth=args.max_depth,
        )
        output_dir_input = Path(confluence_config.output_dir).expanduser()
        output_dir = output_dir_input.resolve()
        if output_dir_input.exists() and not output_dir_input.is_dir():
            exit_with_cli_error(
                (
                    f"Output path is not a directory: {output_dir}. "
                    "Verify --output-dir and use a directory path."
                ),
                command="confluence",
            )
        if confluence_config.max_depth < 0:
            exit_with_cli_error(
                "--max-depth must be greater than or equal to 0.",
                command="confluence",
            )
        space_mode = (
            confluence_config.space_key is not None or confluence_config.space_url is not None
        )
        explicit_max_depth = "--max-depth" in raw_argv
        resolved_space_key: str | None = None
        if confluence_config.space_key is not None and confluence_config.space_url is not None:
            exit_with_cli_error(
                "--space-key and --space-url are mutually exclusive.",
                command="confluence",
            )
        if space_mode:
            if confluence_config.client_mode != "real":
                exit_with_cli_error(
                    "space mode requires --client-mode real",
                    command="confluence",
                )
            if confluence_config.target is not None:
                exit_with_cli_error(
                    "space mode cannot be combined with --target.",
                    command="confluence",
                )
            if confluence_config.tree:
                exit_with_cli_error(
                    "space mode cannot be combined with --tree.",
                    command="confluence",
                )
            if explicit_max_depth:
                exit_with_cli_error(
                    "space mode cannot be combined with --max-depth.",
                    command="confluence",
                )
            try:
                resolved_space_key = (
                    validate_space_key(confluence_config.space_key)
                    if confluence_config.space_key is not None
                    else space_key_from_url_for_base_url(
                        confluence_config.space_url or "",
                        base_url=confluence_config.base_url,
                    )
                )
            except ValueError as exc:
                exit_with_cli_error(str(exc), command="confluence")
        elif confluence_config.target is None:
            exit_with_cli_error(
                "--target, --space-key, or --space-url is required.",
                command="confluence",
            )
        try:
            validate_explicit_tls_paths(
                ca_bundle=None if confluence_config.no_ca_bundle else confluence_config.ca_bundle,
                client_cert_file=confluence_config.client_cert_file,
                client_key_file=confluence_config.client_key_file,
            )
            if confluence_config.client_mode == "real":
                validate_selected_real_tls_paths(confluence_config)
        except ValueError as exc:
            exit_with_cli_error(str(exc), command="confluence")

        target: ResolvedTarget | None = None
        if not space_mode:
            try:
                target = resolve_target_for_base_url(
                    confluence_config.target or "",
                    base_url=confluence_config.base_url,
                )
            except ValueError as exc:
                exit_with_cli_error(
                    str(exc),
                    command="confluence",
                )

        selected_fetch_page: Callable[[ResolvedTarget], dict[str, object]]
        selected_fetch_page_summary: Callable[[ResolvedTarget], dict[str, object]]
        selected_list_child_page_ids: Callable[[ResolvedTarget], list[str]] | None = None
        selected_list_space_page_ids: Callable[[str], list[str]] | None = None
        if confluence_config.client_mode == "real":

            def real_client_tls_kwargs() -> RealClientTLSKwargs:
                kwargs = RealClientTLSKwargs(
                    ca_bundle=confluence_config.ca_bundle,
                    client_cert_file=confluence_config.client_cert_file,
                    client_key_file=confluence_config.client_key_file,
                )
                if confluence_config.no_ca_bundle:
                    kwargs["no_ca_bundle"] = True
                return kwargs

            def selected_fetch_page(resolved_target: ResolvedTarget) -> dict[str, object]:
                return fetch_real_page(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                    **real_client_tls_kwargs(),
                )

            def selected_fetch_page_summary(
                resolved_target: ResolvedTarget,
            ) -> dict[str, object]:
                return fetch_real_page_summary(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                    **real_client_tls_kwargs(),
                )

            def selected_list_child_page_ids(
                resolved_target: ResolvedTarget,
            ) -> list[str]:
                return list_real_child_page_ids(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                    **real_client_tls_kwargs(),
                )

            def selected_list_space_page_ids(space_key: str) -> list[str]:
                return list_real_space_page_ids(
                    space_key,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                    **real_client_tls_kwargs(),
                )
        else:
            selected_fetch_page = fetch_page
            selected_fetch_page_summary = fetch_page

        def _describe_tree_depth(max_depth: int) -> str:
            if max_depth == 0:
                return "root only"
            if max_depth == 1:
                return "root + children"
            if max_depth == 2:
                return "root + children + grandchildren"
            return f"root + descendants through depth {max_depth}"

        def _print_confluence_invocation() -> None:
            ignored_inputs = tuple(
                flag for flag in _CONFLUENCE_REAL_ONLY_INPUT_FLAGS if flag in raw_argv
            )
            content_source = (
                "scaffolded page content"
                if confluence_config.client_mode == "stub"
                else "live Confluence content"
            )
            run_mode = "dry-run" if confluence_config.dry_run else "write"
            print("Confluence adapter invoked")
            print(f"  base_url: {confluence_config.base_url}")
            if space_mode:
                print(f"  space_key: {resolved_space_key}")
                if confluence_config.space_url is not None:
                    print(f"  space_url: {confluence_config.space_url}")
            elif target is not None:
                print(f"  target: {target.raw_value}")
            print(f"  output_dir: {render_user_path(confluence_config.output_dir)}")
            print(f"  client_mode: {confluence_config.client_mode}")
            print(f"  content_source: {content_source}")
            if confluence_config.dry_run:
                mode = "space" if space_mode else "tree" if confluence_config.tree else "single"
                print(f"  mode: {mode}")
            else:
                fetch_scope = (
                    "space" if space_mode else "tree" if confluence_config.tree else "page"
                )
                print(f"  fetch_scope: {fetch_scope}")
            print(f"  run_mode: {run_mode}")
            if confluence_config.tree:
                max_depth = str(confluence_config.max_depth)
                if confluence_config.dry_run:
                    max_depth = f"{max_depth} ({_describe_tree_depth(confluence_config.max_depth)})"
                print(f"  max_depth: {max_depth}")
            if confluence_config.client_mode == "stub" and ignored_inputs:
                print(
                    "  warning: stub mode ignores real-mode Confluence inputs: "
                    f"{', '.join(ignored_inputs)}. Use --client-mode real to apply them."
                )
            if confluence_config.client_mode == "real":
                resolved_tls_inputs = resolve_tls_inputs(
                    ca_bundle=confluence_config.ca_bundle,
                    no_ca_bundle=confluence_config.no_ca_bundle,
                    client_cert_file=confluence_config.client_cert_file,
                    client_key_file=confluence_config.client_key_file,
                )
                tls_inputs: list[str] = []
                if confluence_config.no_ca_bundle:
                    tls_inputs.append("ca_bundle=disabled")
                if resolved_tls_inputs.ca_bundle:
                    tls_inputs.append(
                        f"ca_bundle={render_user_path(resolved_tls_inputs.ca_bundle)}"
                    )
                if resolved_tls_inputs.client_cert_file:
                    tls_inputs.append(
                        f"client_cert_file={render_user_path(resolved_tls_inputs.client_cert_file)}"
                    )
                if resolved_tls_inputs.client_key_file:
                    tls_inputs.append(
                        f"client_key_file={render_user_path(resolved_tls_inputs.client_key_file)}"
                    )
                print(f"  auth_method: {confluence_config.auth_method}")
                print(
                    "  tls_inputs: "
                    f"{', '.join(tls_inputs) if tls_inputs else 'defaults/environment'}"
                )

        def _confluence_debug_lines(
            exc: RuntimeError | ValueError,
        ) -> tuple[str, ...] | None:
            if not confluence_config.debug or not isinstance(exc, ConfluenceRequestError):
                return None

            return (
                f"debug request_url: {exc.request_url}",
                f"debug client_mode: {confluence_config.client_mode}",
                f"debug auth_method: {exc.auth_method}",
                f"debug exception: {exc.underlying_error}",
            )

        def _build_manifest_entry_for_page(
            page: dict[str, object],
            output_path: Path,
        ) -> dict[str, object]:
            page_version = page.get("page_version")
            return build_manifest_entry(
                canonical_id=str(page.get("canonical_id") or ""),
                source_url=str(page.get("source_url", "")),
                output_path=output_path,
                output_dir=confluence_config.output_dir,
                title=str(page["title"]) if page.get("title") else None,
                page_version=(
                    page_version
                    if isinstance(page_version, int) and not isinstance(page_version, bool)
                    else None
                ),
                last_modified=(str(page["last_modified"]) if page.get("last_modified") else None),
            )

        def _display_output_path(path: Path) -> str:
            """Return the consistent user-facing path form for CLI output."""
            return render_user_path(path)

        def _format_page_sync_decision(page_decision: PageSyncDecision) -> str:
            if page_decision.rewrite_reason is None:
                return page_decision.status
            return f"{page_decision.status}: {page_decision.rewrite_reason}"

        def _print_single_page_plan(
            *,
            page_id: str,
            source_url: str,
            output_path: Path,
            manifest_output_path: Path,
            page_decision: PageSyncDecision,
            action: str,
            dry_run: bool,
            stale_count: int | None = None,
            markdown: str | None = None,
        ) -> None:
            print("\nPlan: Confluence run")
            print(f"  resolved_page_id: {page_id}")
            print(f"  source_url: {source_url}")
            print(f"  Artifact: {_display_output_path(output_path)}")
            print(f"  Manifest: {_display_output_path(manifest_output_path)}")
            print(f"  page_status: {page_decision.status}")
            if page_decision.rewrite_reason is not None:
                print(f"  rewrite_reason: {page_decision.rewrite_reason}")
            print(f"  planned_action: {'would ' if dry_run else ''}{action}")
            if dry_run:
                write_count = 1 if action == "write" else 0
                skip_count = 1 if action == "skip" else 0
                _print_confluence_dry_run_summary(
                    mode="single",
                    total_pages=1,
                    new_count=1 if page_decision.status == "new" else 0,
                    changed_count=1 if page_decision.status == "changed" else 0,
                    unchanged_count=1 if page_decision.status == "unchanged" else 0,
                    write_count=write_count,
                    skip_count=skip_count,
                    stale_count=stale_count,
                )
            if markdown is not None:
                print()
                print(markdown)

        def _print_confluence_dry_run_summary(
            *,
            mode: str,
            total_pages: int,
            new_count: int,
            changed_count: int,
            unchanged_count: int,
            write_count: int,
            skip_count: int,
            stale_count: int | None = None,
            space_key: str | None = None,
            discovered_count: int | None = None,
        ) -> None:
            descendant_count = max(total_pages - 1, 0)
            summary_lines = [f"    mode: {mode}"]
            if mode == "space":
                if space_key is not None:
                    summary_lines.append(f"    space_key: {space_key}")
                if discovered_count is not None:
                    summary_lines.append(f"    pages_discovered: {discovered_count}")
                summary_lines.append(f"    pages_in_plan: {total_pages}")
            else:
                summary_lines.append(
                    f"    pages_in_plan: {total_pages} (root 1, descendants {descendant_count})"
                )
            summary_lines.extend(
                [
                    f"    new_pages: {new_count}",
                    f"    changed_pages: {changed_count}",
                    f"    unchanged_pages: {unchanged_count}",
                    f"    would_write: {write_count}",
                    f"    would_skip: {skip_count}",
                ]
            )
            if stale_count is not None:
                summary_lines.append(f"    stale_artifacts: {stale_count}")
            print("  Summary:")
            for line in summary_lines:
                print(line)

        def _print_confluence_write_summary(
            *,
            new_count: int,
            changed_count: int,
            unchanged_count: int,
            write_count: int,
            skip_count: int,
            stale_count: int | None = None,
        ) -> None:
            print(f"\nSummary: wrote {write_count}, skipped {skip_count}")
            print(f"  new_pages: {new_count}")
            print(f"  changed_pages: {changed_count}")
            print(f"  unchanged_pages: {unchanged_count}")
            if stale_count is not None:
                print(f"  stale_artifacts: {stale_count}")
            print(f"  pages_written: {write_count}")
            print(f"  pages_skipped: {skip_count}")

        def _print_stub_tree_mode_note() -> None:
            if not (confluence_config.tree and confluence_config.client_mode == "stub"):
                return

            print(
                "  note: stub mode does not support descendant discovery; "
                "use --client-mode real to discover descendants from Confluence."
            )

        def _print_tree_walk_progress(progress: TreeWalkProgress) -> None:
            print(
                "Tree progress: "
                f"depth {progress.depth}, "
                f"discovered {progress.discovered_pages}, "
                f"fetched {progress.fetched_pages}, "
                f"planned {progress.discovered_pages}"
            )

        def _should_report_fetch_progress(*, fetched_count: int, total_count: int) -> bool:
            return total_count <= 5 or fetched_count == total_count or fetched_count % 10 == 0

        if space_mode:
            previous_manifest_index = load_previous_manifest_index(confluence_config.output_dir)
            space_fetch_page = (
                selected_fetch_page
                if previous_manifest_index is None
                else selected_fetch_page_summary
            )
            if selected_list_space_page_ids is None or resolved_space_key is None:
                exit_with_cli_error(
                    "space mode requires --client-mode real",
                    command="confluence",
                )
            assert selected_list_space_page_ids is not None
            assert resolved_space_key is not None

            print(f"Space progress: discovery started, space_key {resolved_space_key}")
            try:
                discovered_page_ids = sorted(set(selected_list_space_page_ids(resolved_space_key)))
                print(
                    "Space progress: "
                    f"discovered {len(discovered_page_ids)} pages, "
                    f"planned {len(discovered_page_ids)}"
                )
                pages: list[dict[str, object]] = []
                for index, page_id in enumerate(discovered_page_ids, start=1):
                    pages.append(
                        space_fetch_page(
                            ResolvedTarget(
                                raw_value=page_id,
                                page_id=page_id,
                                page_url=None,
                            )
                        )
                    )
                    if _should_report_fetch_progress(
                        fetched_count=index,
                        total_count=len(discovered_page_ids),
                    ):
                        print(
                            "Space fetch progress: "
                            f"fetched {index}/{len(discovered_page_ids)}, "
                            f"planned {len(discovered_page_ids)}"
                        )
            except (RuntimeError, ValueError) as exc:
                exit_with_cli_error(
                    str(exc),
                    command="confluence",
                    debug_lines=_confluence_debug_lines(exc),
                )

            _print_confluence_invocation()
            space_page_records: list[tuple[dict[str, object], Path, PageSyncDecision, str]] = []
            for page in pages:
                canonical_id = str(page.get("canonical_id") or "")
                output_path = markdown_path(confluence_config.output_dir, canonical_id)
                page_decision = classify_page_sync(
                    confluence_config.output_dir,
                    previous_manifest_index,
                    page=page,
                    output_path=output_path,
                )
                action = "skip" if page_decision.status == "unchanged" else "write"
                space_page_records.append((page, output_path, page_decision, action))
            stale_artifacts = [
                (artifact.canonical_id, artifact.output_path)
                for artifact in find_stale_artifacts(
                    confluence_config.output_dir,
                    previous_manifest_index,
                    current_output_paths=[
                        output_path.relative_to(Path(confluence_config.output_dir)).as_posix()
                        for _page, output_path, _page_decision, _action in space_page_records
                    ],
                )
            ]

            write_count = sum(
                1
                for _page, _output_path, _page_decision, action in space_page_records
                if action == "write"
            )
            skip_count = len(space_page_records) - write_count
            new_count = sum(
                1
                for _page, _output_path, page_decision, _action in space_page_records
                if page_decision.status == "new"
            )
            changed_count = sum(
                1
                for _page, _output_path, page_decision, _action in space_page_records
                if page_decision.status == "changed"
            )
            unchanged_count = len(space_page_records) - new_count - changed_count
            manifest_output_path = manifest_path(confluence_config.output_dir)

            print("\nPlan: Confluence run")
            print(f"  space_key: {resolved_space_key}")
            print(f"  Manifest: {_display_output_path(manifest_output_path)}")
            print(f"  pages_discovered: {len(discovered_page_ids)}")
            print(f"  pages_planned: {len(space_page_records)}")

            if confluence_config.dry_run:
                _print_confluence_dry_run_summary(
                    mode="space",
                    total_pages=len(space_page_records),
                    new_count=new_count,
                    changed_count=changed_count,
                    unchanged_count=unchanged_count,
                    write_count=write_count,
                    skip_count=skip_count,
                    stale_count=len(stale_artifacts),
                    space_key=resolved_space_key,
                    discovered_count=len(discovered_page_ids),
                )
                print_stale_artifacts(confluence_config.output_dir, stale_artifacts)
                for _page, output_path, page_decision, action in space_page_records:
                    print(
                        "  would "
                        f"{action} {_display_output_path(output_path)} "
                        f"({_format_page_sync_decision(page_decision)})"
                    )
                print_dry_run_complete()
                return 0

            files = [
                _build_manifest_entry_for_page(page, output_path)
                for page, output_path, _page_decision, _action in space_page_records
            ]

            space_pages_to_write: dict[str, dict[str, object]] = {}
            pages_needing_fetch = sum(
                1
                for page, _output_path, _page_decision, action in space_page_records
                if action == "write" and page.get("content") is None
            )
            fetched_write_pages = 0
            if pages_needing_fetch > 0:
                print(
                    "Space write fetch progress: "
                    f"fetched 0/{pages_needing_fetch}, "
                    f"skipped {skip_count}, "
                    f"planned {len(space_page_records)}"
                )
            try:
                for page, _output_path, _page_decision, action in space_page_records:
                    if action == "skip":
                        continue

                    if page.get("content") is not None:
                        space_pages_to_write[str(page.get("canonical_id") or "")] = page
                        continue

                    page_id = str(page.get("canonical_id") or "")
                    space_pages_to_write[page_id] = selected_fetch_page(
                        ResolvedTarget(
                            raw_value=page_id,
                            page_id=page_id,
                            page_url=None,
                        )
                    )
                    fetched_write_pages += 1
                    if _should_report_fetch_progress(
                        fetched_count=fetched_write_pages,
                        total_count=pages_needing_fetch,
                    ):
                        print(
                            "Space write fetch progress: "
                            f"fetched {fetched_write_pages}/{pages_needing_fetch}, "
                            f"skipped {skip_count}, "
                            f"planned {len(space_page_records)}"
                        )
            except (RuntimeError, ValueError) as exc:
                exit_with_cli_error(
                    str(exc),
                    command="confluence",
                    debug_lines=_confluence_debug_lines(exc),
                )

            try:
                for page, output_path, page_decision, action in space_page_records:
                    if action == "skip":
                        print(
                            "\nSkipped: "
                            f"{_display_output_path(output_path)} "
                            f"({_format_page_sync_decision(page_decision)})"
                        )
                        continue

                    page_to_write = space_pages_to_write[str(page.get("canonical_id") or "")]
                    markdown = normalize_to_markdown(page_to_write)
                    write_markdown(
                        confluence_config.output_dir,
                        str(page_to_write.get("canonical_id") or ""),
                        markdown,
                    )
                    print(
                        "\nWrote: "
                        f"{_display_output_path(output_path)} "
                        f"({_format_page_sync_decision(page_decision)})"
                    )

                manifest = write_manifest(confluence_config.output_dir, files)
            except OSError as exc:
                exit_with_output_error(
                    confluence_config.output_dir,
                    command="confluence",
                    exc=exc,
                )
            _print_confluence_write_summary(
                new_count=new_count,
                changed_count=changed_count,
                unchanged_count=unchanged_count,
                write_count=write_count,
                skip_count=skip_count,
                stale_count=len(stale_artifacts),
            )
            print_stale_artifacts(confluence_config.output_dir, stale_artifacts)
            print(f"Manifest: {_display_output_path(manifest)}")
            print_write_complete(output_dir)
            return 0

        if confluence_config.tree:
            if target is None:
                exit_with_cli_error(
                    "--target is required for tree mode.",
                    command="confluence",
                )
            assert target is not None
            previous_manifest_index = load_previous_manifest_index(confluence_config.output_dir)
            tree_fetch_page = (
                selected_fetch_page
                if previous_manifest_index is None
                else selected_fetch_page_summary
            )
            print(f"Tree progress: traversal started, max_depth {confluence_config.max_depth}")
            if confluence_config.client_mode == "real":
                try:
                    root_page_id, pages = walk_pages(
                        target,
                        max_depth=confluence_config.max_depth,
                        fetch_page=tree_fetch_page,
                        list_child_page_ids=selected_list_child_page_ids,
                        progress_callback=_print_tree_walk_progress,
                    )
                except (RuntimeError, ValueError) as exc:
                    exit_with_cli_error(
                        str(exc),
                        command="confluence",
                        debug_lines=_confluence_debug_lines(exc),
                    )
            else:
                root_page_id, pages = walk_pages(
                    target,
                    max_depth=confluence_config.max_depth,
                    fetch_page=tree_fetch_page,
                    list_child_page_ids=selected_list_child_page_ids,
                    progress_callback=_print_tree_walk_progress,
                )
            _print_confluence_invocation()
            page_records: list[tuple[dict[str, object], Path, PageSyncDecision, str]] = []
            for page in pages:
                canonical_id = str(page.get("canonical_id") or "")
                output_path = markdown_path(confluence_config.output_dir, canonical_id)
                page_decision = classify_page_sync(
                    confluence_config.output_dir,
                    previous_manifest_index,
                    page=page,
                    output_path=output_path,
                )
                action = "skip" if page_decision.status == "unchanged" else "write"
                page_records.append((page, output_path, page_decision, action))
            stale_artifacts = [
                (artifact.canonical_id, artifact.output_path)
                for artifact in find_stale_artifacts(
                    confluence_config.output_dir,
                    previous_manifest_index,
                    current_output_paths=[
                        output_path.relative_to(Path(confluence_config.output_dir)).as_posix()
                        for _page, output_path, _page_decision, _action in page_records
                    ],
                )
            ]

            write_count = sum(
                1
                for _page, _output_path, _page_decision, action in page_records
                if action == "write"
            )
            skip_count = len(page_records) - write_count
            new_count = sum(
                1
                for _page, _output_path, page_decision, _action in page_records
                if page_decision.status == "new"
            )
            changed_count = sum(
                1
                for _page, _output_path, page_decision, _action in page_records
                if page_decision.status == "changed"
            )
            unchanged_count = len(page_records) - new_count - changed_count
            manifest_output_path = manifest_path(confluence_config.output_dir)

            print("\nPlan: Confluence run")
            print(f"  resolved_root_page_id: {root_page_id} (root page)")
            print(f"  max_depth: {confluence_config.max_depth}")
            print(f"  Manifest: {_display_output_path(manifest_output_path)}")
            print(f"  pages_in_tree: {len(page_records)} (root + descendants)")
            _print_stub_tree_mode_note()

            if confluence_config.dry_run:
                _print_confluence_dry_run_summary(
                    mode="tree",
                    total_pages=len(page_records),
                    new_count=new_count,
                    changed_count=changed_count,
                    unchanged_count=unchanged_count,
                    write_count=write_count,
                    skip_count=skip_count,
                    stale_count=len(stale_artifacts),
                )
                print_stale_artifacts(confluence_config.output_dir, stale_artifacts)
                for _page, output_path, page_decision, action in page_records:
                    print(
                        "  would "
                        f"{action} {_display_output_path(output_path)} "
                        f"({_format_page_sync_decision(page_decision)})"
                    )
                print_dry_run_complete()
                return 0

            files = [
                _build_manifest_entry_for_page(page, output_path)
                for page, output_path, _page_decision, _action in page_records
            ]

            pages_to_write: dict[str, dict[str, object]] = {}
            pages_needing_fetch = sum(
                1
                for page, _output_path, _page_decision, action in page_records
                if action == "write" and page.get("content") is None
            )
            fetched_write_pages = 0
            if pages_needing_fetch > 0:
                print(
                    "Tree fetch progress: "
                    f"fetched 0/{pages_needing_fetch}, "
                    f"skipped {skip_count}, "
                    f"planned {len(page_records)}"
                )
            try:
                for page, _output_path, _page_decision, action in page_records:
                    if action == "skip":
                        continue

                    if page.get("content") is not None:
                        pages_to_write[str(page.get("canonical_id") or "")] = page
                        continue

                    page_id = str(page.get("canonical_id") or "")
                    pages_to_write[page_id] = selected_fetch_page(
                        ResolvedTarget(
                            raw_value=page_id,
                            page_id=page_id,
                            page_url=None,
                        )
                    )
                    fetched_write_pages += 1
                    if _should_report_fetch_progress(
                        fetched_count=fetched_write_pages,
                        total_count=pages_needing_fetch,
                    ):
                        print(
                            "Tree fetch progress: "
                            f"fetched {fetched_write_pages}/{pages_needing_fetch}, "
                            f"skipped {skip_count}, "
                            f"planned {len(page_records)}"
                        )
            except (RuntimeError, ValueError) as exc:
                exit_with_cli_error(
                    str(exc),
                    command="confluence",
                    debug_lines=_confluence_debug_lines(exc),
                )

            try:
                for page, output_path, page_decision, action in page_records:
                    if action == "skip":
                        print(
                            "\nSkipped: "
                            f"{_display_output_path(output_path)} "
                            f"({_format_page_sync_decision(page_decision)})"
                        )
                        continue

                    page_to_write = pages_to_write[str(page.get("canonical_id") or "")]
                    markdown = normalize_to_markdown(page_to_write)
                    write_markdown(
                        confluence_config.output_dir,
                        str(page_to_write.get("canonical_id") or ""),
                        markdown,
                    )
                    print(
                        "\nWrote: "
                        f"{_display_output_path(output_path)} "
                        f"({_format_page_sync_decision(page_decision)})"
                    )

                manifest = write_manifest_with_context(
                    confluence_config.output_dir,
                    files,
                    root_page_id=root_page_id,
                    max_depth=confluence_config.max_depth,
                )
            except OSError as exc:
                exit_with_output_error(
                    confluence_config.output_dir,
                    command="confluence",
                    exc=exc,
                )
            _print_confluence_write_summary(
                new_count=new_count,
                changed_count=changed_count,
                unchanged_count=unchanged_count,
                write_count=write_count,
                skip_count=skip_count,
                stale_count=len(stale_artifacts),
            )
            print_stale_artifacts(confluence_config.output_dir, stale_artifacts)
            print(f"Manifest: {_display_output_path(manifest)}")
            print_write_complete(output_dir)
            return 0

        if target is None:
            exit_with_cli_error(
                "--target is required for single-page mode.",
                command="confluence",
            )
        assert target is not None

        previous_manifest_index = load_previous_manifest_index(confluence_config.output_dir)
        try:
            page = (
                selected_fetch_page(target)
                if previous_manifest_index is None
                else selected_fetch_page_summary(target)
            )
        except (RuntimeError, ValueError) as exc:
            exit_with_cli_error(
                str(exc),
                command="confluence",
                debug_lines=_confluence_debug_lines(exc),
            )

        _print_confluence_invocation()
        page_id = str(page["canonical_id"])
        output_path = markdown_path(confluence_config.output_dir, page_id)
        manifest_output_path = manifest_path(confluence_config.output_dir)
        page_decision = classify_page_sync(
            confluence_config.output_dir,
            previous_manifest_index,
            page=page,
            output_path=output_path,
        )
        stale_artifacts = [
            (artifact.canonical_id, artifact.output_path)
            for artifact in find_stale_artifacts(
                confluence_config.output_dir,
                previous_manifest_index,
                current_output_paths=[
                    output_path.relative_to(Path(confluence_config.output_dir)).as_posix()
                ],
            )
        ]
        action = "skip" if page_decision.status == "unchanged" else "write"

        if confluence_config.dry_run:
            planned_page = page
            if action == "write" and page.get("content") is None:
                try:
                    planned_page = selected_fetch_page(target)
                except (RuntimeError, ValueError) as exc:
                    exit_with_cli_error(
                        str(exc),
                        command="confluence",
                        debug_lines=_confluence_debug_lines(exc),
                    )
            planned_markdown = normalize_to_markdown(planned_page) if action == "write" else None
            _print_single_page_plan(
                page_id=page_id,
                source_url=str(page.get("source_url", "")),
                output_path=output_path,
                manifest_output_path=manifest_output_path,
                page_decision=page_decision,
                action=action,
                dry_run=True,
                stale_count=len(stale_artifacts),
                markdown=planned_markdown,
            )
            print_stale_artifacts(confluence_config.output_dir, stale_artifacts)
            print_dry_run_complete()
            return 0

        _print_single_page_plan(
            page_id=page_id,
            source_url=str(page.get("source_url", "")),
            output_path=output_path,
            manifest_output_path=manifest_output_path,
            page_decision=page_decision,
            action=action,
            dry_run=False,
            stale_count=len(stale_artifacts),
        )

        try:
            if action == "write":
                page_to_write = (
                    page if page.get("content") is not None else selected_fetch_page(target)
                )
                markdown = normalize_to_markdown(page_to_write)
                write_markdown(
                    confluence_config.output_dir,
                    page_id,
                    markdown,
                )
                print(
                    "\nWrote: "
                    f"{_display_output_path(output_path)} "
                    f"({_format_page_sync_decision(page_decision)})"
                )
            else:
                print(
                    "\nSkipped: "
                    f"{_display_output_path(output_path)} "
                    f"({_format_page_sync_decision(page_decision)})"
                )

            manifest = write_manifest(
                confluence_config.output_dir,
                [
                    _build_manifest_entry_for_page(page, output_path),
                ],
            )
        except (RuntimeError, ValueError) as exc:
            exit_with_cli_error(
                str(exc),
                command="confluence",
                debug_lines=_confluence_debug_lines(exc),
            )
        except OSError as exc:
            exit_with_output_error(
                confluence_config.output_dir,
                command="confluence",
                exc=exc,
            )
        write_count = 1 if action == "write" else 0
        skip_count = 1 if action == "skip" else 0
        _print_confluence_write_summary(
            new_count=1 if page_decision.status == "new" else 0,
            changed_count=1 if page_decision.status == "changed" else 0,
            unchanged_count=1 if page_decision.status == "unchanged" else 0,
            write_count=write_count,
            skip_count=skip_count,
            stale_count=len(stale_artifacts),
        )
        print_stale_artifacts(confluence_config.output_dir, stale_artifacts)
        print(f"Manifest: {_display_output_path(manifest)}")
        print_write_complete(output_dir)
        return 0

    if args.command == "bundle":
        from knowledge_adapters.bundle import (
            SplitBundlePlan,
            load_bundle_plan,
            plan_split_bundle,
            render_bundle_markdown,
            render_bundle_sections,
            write_bundle,
            write_split_bundle,
        )

        output_path_input = Path(args.output).expanduser()
        output_path = output_path_input.resolve()
        if output_path_input.exists() and output_path_input.is_dir():
            exit_with_cli_error(
                (
                    f"Bundle output path is a directory: {output_path}. "
                    "Verify --output and use a file path."
                ),
                command="bundle",
            )

        try:
            bundle_plan = load_bundle_plan(
                args.inputs,
                order=args.order,
                include_patterns=args.include,
                exclude_patterns=args.exclude,
                changed_only=args.changed_only,
                baseline_manifest=args.baseline_manifest,
            )
            split_bundle_plan: SplitBundlePlan | None = None
            bundle_markdown: str | None = None
            if args.max_bytes is None:
                bundle_markdown = render_bundle_markdown(
                    bundle_plan.artifacts,
                    header_mode=args.header_mode,
                )
            else:
                sections = render_bundle_sections(
                    bundle_plan.artifacts,
                    header_mode=args.header_mode,
                )
                split_bundle_plan = plan_split_bundle(
                    args.output,
                    sections,
                    max_bytes=args.max_bytes,
                )
        except ValueError as exc:
            exit_with_cli_error(str(exc), command="bundle")

        print("Bundle command invoked")
        print(f"  inputs: {len(args.inputs)}")
        print(f"  output: {render_user_path(args.output)}")
        if args.max_bytes is not None:
            print(f"  max_bytes: {args.max_bytes}")
        print(f"  ordering: {describe_bundle_order(args.order)}")
        print(f"  header_mode: {describe_header_mode(args.header_mode)}")
        if args.include:
            print(f"  include_filters: {len(args.include)}")
        if args.exclude:
            print(f"  exclude_filters: {len(args.exclude)}")
        if args.changed_only:
            print("  changed_only: true")
            if bundle_plan.baseline_manifest is not None:
                print(f"  baseline_manifest: {render_user_path(bundle_plan.baseline_manifest)}")

        print("\nPlan: Bundle run")
        for manifest in bundle_plan.manifests:
            print(f"  manifest: {render_user_path(manifest)}")
        print(f"  artifacts_selected: {len(bundle_plan.artifacts)}")
        print(f"  duplicates_skipped: {len(bundle_plan.duplicate_canonical_ids)}")
        if args.changed_only:
            print(f"  unchanged_skipped: {bundle_plan.unchanged_count}")
        if args.include:
            for pattern in args.include:
                print(f"  include: {pattern}")
        if args.exclude:
            for pattern in args.exclude:
                print(f"  exclude: {pattern}")
        if args.include or args.exclude:
            print(f"  artifacts_filtered_out: {bundle_plan.filtered_out_count}")
        if split_bundle_plan is not None:
            print(f"  output_files: {len(split_bundle_plan.output_files)}")
            if split_bundle_plan.oversized_sections:
                print(f"  oversized_sections: {len(split_bundle_plan.oversized_sections)}")
                for oversized_section in split_bundle_plan.oversized_sections:
                    print(
                        "  oversized: "
                        f"{oversized_section.canonical_id} "
                        f"({oversized_section.byte_count} bytes > {args.max_bytes} max)"
                    )
        print("  action: write")

        try:
            if split_bundle_plan is None:
                assert bundle_markdown is not None
                written_bundle = write_bundle(args.output, bundle_markdown)
                written_split_bundle = None
            else:
                written_split_bundle = write_split_bundle(split_bundle_plan)
                written_bundle = None
        except OSError as exc:
            exit_with_bundle_output_error(args.output, exc=exc)

        if written_split_bundle is None:
            assert written_bundle is not None
            print(f"\nWrote bundle: {render_user_path(written_bundle)}")
        else:
            print(f"\nWrote split bundle files: {len(written_split_bundle.output_files)}")
            for output_file in written_split_bundle.output_files:
                print(
                    "  file: "
                    f"{render_user_path(output_file.path)} "
                    f"({output_file.artifact_count} artifacts, {output_file.byte_count} bytes)"
                )
        if args.changed_only:
            print(
                "\nSummary: bundled "
                f"{len(bundle_plan.artifacts)}, skipped "
                f"{bundle_plan.unchanged_count} unchanged, skipped "
                f"{len(bundle_plan.duplicate_canonical_ids)} duplicates"
            )
        elif args.include or args.exclude:
            print(
                "\nSummary: bundled "
                f"{len(bundle_plan.artifacts)}, filtered out "
                f"{bundle_plan.filtered_out_count}, skipped "
                f"{len(bundle_plan.duplicate_canonical_ids)} duplicates"
            )
        else:
            print(
                "\nSummary: bundled "
                f"{len(bundle_plan.artifacts)}, skipped "
                f"{len(bundle_plan.duplicate_canonical_ids)} duplicates"
            )
        if written_split_bundle is not None:
            print(
                "Summary: wrote "
                f"{len(written_split_bundle.output_files)} files, "
                f"{len(written_split_bundle.oversized_sections)} oversized sections"
            )
        if written_split_bundle is None:
            assert written_bundle is not None
            print(f"Output path: {render_user_path(written_bundle)}")
            print(f"\nWrite complete. Bundle created at {render_user_path(written_bundle)}")
        else:
            first_output_file = written_split_bundle.output_files[0]
            print(f"Output files: {len(written_split_bundle.output_files)}")
            print(f"First output path: {render_user_path(first_output_file.path)}")
            print(
                "\nWrite complete. Bundle split into "
                f"{len(written_split_bundle.output_files)} files under "
                f"{render_user_path(first_output_file.path.parent)}"
            )
        return 0

    if args.command == "local_files":
        from knowledge_adapters.local_files.client import fetch_file
        from knowledge_adapters.local_files.config import LocalFilesConfig
        from knowledge_adapters.local_files.normalize import normalize_to_markdown
        from knowledge_adapters.local_files.writer import write_markdown
        from knowledge_adapters.manifest import (
            build_manifest_entry,
            write_manifest,
        )
        from knowledge_adapters.manifest_stale import (
            find_stale_artifacts,
            load_previous_manifest_index,
            load_previous_manifest_output_index,
        )

        local_files_config = LocalFilesConfig(
            file_path=args.file_path,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )

        output_dir_input = Path(local_files_config.output_dir).expanduser()
        output_dir = output_dir_input.resolve()
        if output_dir_input.exists() and not output_dir_input.is_dir():
            exit_with_cli_error(
                (
                    f"Output path is not a directory: {output_dir}. "
                    "Verify --output-dir and use a directory path."
                ),
                command="local_files",
            )

        try:
            page = fetch_file(local_files_config.file_path)
        except ValueError as exc:
            exit_with_cli_error(str(exc), command="local_files")
        markdown = normalize_to_markdown(page)

        print("Local files adapter invoked")
        print(f"  file_path: {render_user_path(local_files_config.file_path)}")
        print(f"  output_dir: {render_user_path(local_files_config.output_dir)}")
        print(f"  run_mode: {'dry-run' if local_files_config.dry_run else 'write'}")

        input_path = Path(local_files_config.file_path)
        output_name = input_path.stem or input_path.name
        resolved_input_path = render_user_path(input_path)
        manifest_output_path = output_dir / "manifest.json"
        output_path = output_dir / "pages" / f"{output_name}.md"
        manifest_entry_output_path = output_dir_input / "pages" / f"{output_name}.md"
        planned_output_path = output_path.relative_to(output_dir).as_posix()

        try:
            previous_manifest_index = load_previous_manifest_index(local_files_config.output_dir)
            previous_manifest_output_index = load_previous_manifest_output_index(
                local_files_config.output_dir
            )
        except RuntimeError as exc:
            exit_with_cli_error(str(exc), command="local_files")

        prior_source_path = None
        if previous_manifest_output_index is not None:
            prior_source_path = previous_manifest_output_index.get(planned_output_path)
        current_source_path = str(page["canonical_id"])
        if prior_source_path is not None and prior_source_path != current_source_path:
            exit_with_local_files_artifact_collision(
                output_path=output_path,
                manifest_output_path=manifest_output_path,
                prior_source_path=prior_source_path,
                current_source_path=current_source_path,
            )
        stale_artifacts = [
            (artifact.canonical_id, artifact.output_path)
            for artifact in find_stale_artifacts(
                local_files_config.output_dir,
                previous_manifest_index,
                current_output_paths=[planned_output_path],
            )
        ]

        print("\nPlan: Local files run")
        print(f"  resolved_file_path: {resolved_input_path}")
        print(f"  source_url: {page.get('source_url', '')}")
        print(f"  Artifact path: {render_user_path(output_path)}")
        print(f"  Manifest path: {render_user_path(manifest_output_path)}")
        content = str(page.get("content", ""))
        if content:
            print("  content_status: UTF-8 text with content")
        else:
            print(
                "  content_status: empty UTF-8 file; output will contain metadata "
                "and an empty content section"
            )
        print(f"  action: {'would write' if local_files_config.dry_run else 'write'}")
        if local_files_config.dry_run:
            print("  Summary: would write 1, would skip 0")
            print(f"  stale_artifacts: {len(stale_artifacts)}")
            print_stale_artifacts(local_files_config.output_dir, stale_artifacts)
            print()
            print(markdown)
            print_dry_run_complete()
            return 0

        try:
            write_markdown(
                local_files_config.output_dir,
                output_name,
                markdown,
            )
            manifest = write_manifest(
                local_files_config.output_dir,
                [
                    build_manifest_entry(
                        canonical_id=str(page["canonical_id"]),
                        source_url=str(page.get("source_url", "")),
                        output_path=manifest_entry_output_path,
                        output_dir=local_files_config.output_dir,
                        title=str(page["title"]) if page.get("title") else None,
                    )
                ],
            )
        except OSError as exc:
            exit_with_output_error(
                local_files_config.output_dir,
                command="local_files",
                exc=exc,
            )
        print(f"\nWrote: {render_user_path(output_path)}")
        print("\nSummary: wrote 1, skipped 0")
        print(f"  stale_artifacts: {len(stale_artifacts)}")
        print_stale_artifacts(local_files_config.output_dir, stale_artifacts)
        print(f"Artifact path: {render_user_path(output_path)}")
        print(f"Manifest path: {render_user_path(manifest)}")
        print_write_complete(output_dir)
        return 0

    if args.command == "github_metadata":
        import hashlib

        from knowledge_adapters.github_metadata.client import (
            GitHubIssue,
            GitHubMetadataRequestError,
            GitHubPullRequest,
            list_repository_issues,
            list_repository_pull_requests,
            resolve_base_urls,
        )
        from knowledge_adapters.github_metadata.config import GitHubMetadataConfig
        from knowledge_adapters.github_metadata.normalize import (
            normalize_issue_to_markdown,
            normalize_pull_request_to_markdown,
        )
        from knowledge_adapters.github_metadata.writer import (
            markdown_path as github_metadata_markdown_path,
        )
        from knowledge_adapters.github_metadata.writer import (
            write_markdown as write_github_metadata_markdown,
        )
        from knowledge_adapters.manifest import write_manifest
        from knowledge_adapters.manifest_stale import (
            find_stale_artifacts,
            load_previous_manifest_index,
        )

        github_metadata_config = GitHubMetadataConfig(
            repo=args.repo,
            resource_type=args.resource_type,
            base_url=args.base_url,
            token_env=args.token_env,
            output_dir=args.output_dir,
            state=args.state,
            since=args.since,
            max_items=args.max_items,
            include_issue_comments=args.include_issue_comments,
            dry_run=args.dry_run,
        )

        output_dir_input = Path(github_metadata_config.output_dir).expanduser()
        output_dir = output_dir_input.resolve()
        if output_dir_input.exists() and not output_dir_input.is_dir():
            exit_with_cli_error(
                (
                    f"Output path is not a directory: {output_dir}. "
                    "Verify --output-dir and use a directory path."
                ),
                command="github_metadata",
            )

        try:
            base_urls = resolve_base_urls(github_metadata_config.base_url)
            records: tuple[GitHubIssue | GitHubPullRequest, ...]
            if github_metadata_config.resource_type == "issue":
                records = list_repository_issues(
                    repo=github_metadata_config.repo,
                    base_url=github_metadata_config.base_url,
                    token_env=github_metadata_config.token_env,
                    state=github_metadata_config.state,
                    since=github_metadata_config.since,
                    max_items=github_metadata_config.max_items,
                    include_issue_comments=github_metadata_config.include_issue_comments,
                )
            else:
                records = list_repository_pull_requests(
                    repo=github_metadata_config.repo,
                    base_url=github_metadata_config.base_url,
                    token_env=github_metadata_config.token_env,
                    state=github_metadata_config.state,
                    since=github_metadata_config.since,
                    max_items=github_metadata_config.max_items,
                )
        except (GitHubMetadataRequestError, ValueError) as exc:
            exit_with_cli_error(str(exc), command="github_metadata")

        print("GitHub metadata adapter invoked")
        print(f"  repo: {github_metadata_config.repo}")
        print(f"  web_root: {base_urls.web_root}")
        print(f"  api_root: {base_urls.api_root}")
        print(f"  token_env: {github_metadata_config.token_env}")
        print(f"  output_dir: {render_user_path(github_metadata_config.output_dir)}")
        print(f"  resource_type: {github_metadata_config.resource_type}")
        print(f"  state: {github_metadata_config.state}")
        if github_metadata_config.since is not None:
            print(f"  since: {github_metadata_config.since}")
        if github_metadata_config.max_items is not None:
            print(f"  max_items: {github_metadata_config.max_items}")
        if (
            github_metadata_config.resource_type == "issue"
            and github_metadata_config.include_issue_comments
        ):
            print("  include_issue_comments: true")
        print(f"  run_mode: {'dry-run' if github_metadata_config.dry_run else 'write'}")

        try:
            previous_manifest_index = load_previous_manifest_index(
                github_metadata_config.output_dir
            )
        except RuntimeError as exc:
            exit_with_cli_error(str(exc), command="github_metadata")

        print("\nPlan: GitHub metadata run")
        resource_label = (
            "issue" if github_metadata_config.resource_type == "issue" else "pull_request"
        )
        resource_count_label = (
            "issues_planned"
            if github_metadata_config.resource_type == "issue"
            else "pull_requests_planned"
        )
        print(f"  resource_type: {github_metadata_config.resource_type}")
        print(f"  {resource_count_label}: {len(records)}")

        record_markdowns: dict[int, str] = {}
        github_manifest_entries: list[dict[str, object]] = []
        github_written_output_paths: list[Path] = []
        for record in records:
            normalized_record = {
                "repo": record.repo,
                "number": record.number,
                "title": record.title,
                "state": record.state,
                "author": record.author,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "source_url": record.source_url,
                "body": record.body,
            }
            if github_metadata_config.resource_type == "issue":
                assert isinstance(record, GitHubIssue)
                if record.comments:
                    normalized_record["comments"] = [
                        {
                            "author": comment.author,
                            "created_at": comment.created_at,
                            "updated_at": comment.updated_at,
                            "body": comment.body,
                        }
                        for comment in record.comments
                    ]
                markdown = normalize_issue_to_markdown(normalized_record)
            else:
                markdown = normalize_pull_request_to_markdown(normalized_record)
            output_path = github_metadata_markdown_path(
                github_metadata_config.output_dir,
                github_metadata_config.resource_type,
                record.number,
            )
            record_markdowns[record.number] = markdown
            github_written_output_paths.append(output_path)
            github_manifest_entries.append(
                {
                    "canonical_id": record.canonical_id,
                    "source_url": record.source_url,
                    "title": record.title,
                    "repo": record.repo,
                    "resource_type": github_metadata_config.resource_type,
                    "number": record.number,
                    "state": record.state,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "author": record.author,
                    "content_hash": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                    "output_path": output_path.relative_to(
                        Path(github_metadata_config.output_dir)
                    ).as_posix(),
                }
            )
        stale_artifacts = [
            (artifact.canonical_id, artifact.output_path)
            for artifact in find_stale_artifacts(
                github_metadata_config.output_dir,
                previous_manifest_index,
                current_output_paths=[
                    str(entry["output_path"]) for entry in github_manifest_entries
                ],
            )
        ]

        for record, output_path in zip(records, github_written_output_paths, strict=True):
            print(f"\n  {resource_label}: #{record.number}")
            print(f"  title: {record.title}")
            print(f"  source_url: {record.source_url}")
            print(f"  Artifact path: {render_user_path(output_path)}")
            if record.body:
                print("  body_status: markdown/text with content")
            else:
                print(
                    "  body_status: empty "
                    f"{resource_label.replace('_', ' ')} body; output will include an "
                    "empty-body marker"
                )
            print(f"  action: {'would write' if github_metadata_config.dry_run else 'write'}")

        manifest_output_path = output_dir / "manifest.json"
        if github_metadata_config.dry_run:
            print(f"\nSummary: would write {len(records)}, would skip 0")
            print(f"  stale_artifacts: {len(stale_artifacts)}")
            print_stale_artifacts(github_metadata_config.output_dir, stale_artifacts)
            print(f"Manifest path: {render_user_path(manifest_output_path)}")
            print_dry_run_complete()
            return 0

        try:
            for record in records:
                write_github_metadata_markdown(
                    github_metadata_config.output_dir,
                    github_metadata_config.resource_type,
                    record.number,
                    record_markdowns[record.number],
                )
            manifest = write_manifest(
                github_metadata_config.output_dir,
                github_manifest_entries,
            )
        except OSError as exc:
            exit_with_output_error(
                github_metadata_config.output_dir,
                command="github_metadata",
                exc=exc,
            )

        for output_path in github_written_output_paths:
            print(f"\nWrote: {render_user_path(output_path)}")
        print(f"\nSummary: wrote {len(records)}, skipped 0")
        print(f"  stale_artifacts: {len(stale_artifacts)}")
        print_stale_artifacts(github_metadata_config.output_dir, stale_artifacts)
        print(f"Manifest path: {render_user_path(manifest)}")
        print_write_complete(output_dir)
        return 0

    if args.command == "git_repo":
        import hashlib

        from knowledge_adapters.git_repo.client import fetch_repo_snapshot
        from knowledge_adapters.git_repo.config import GitRepoConfig
        from knowledge_adapters.git_repo.normalize import normalize_to_markdown
        from knowledge_adapters.git_repo.writer import (
            markdown_path as git_repo_markdown_path,
        )
        from knowledge_adapters.git_repo.writer import (
            write_markdown as write_git_repo_markdown,
        )
        from knowledge_adapters.manifest import (
            build_manifest_entry,
            write_manifest,
        )
        from knowledge_adapters.manifest_stale import (
            find_stale_artifacts,
            load_previous_manifest_index,
        )

        git_repo_config = GitRepoConfig(
            repo_url=args.repo_url,
            output_dir=args.output_dir,
            ref=args.ref,
            include=tuple(args.include),
            exclude=tuple(args.exclude),
            subdir=args.subdir,
            dry_run=args.dry_run,
        )

        output_dir_input = Path(git_repo_config.output_dir).expanduser()
        output_dir = output_dir_input.resolve()
        if output_dir_input.exists() and not output_dir_input.is_dir():
            exit_with_cli_error(
                (
                    f"Output path is not a directory: {output_dir}. "
                    "Verify --output-dir and use a directory path."
                ),
                command="git_repo",
            )

        try:
            snapshot = fetch_repo_snapshot(
                git_repo_config.repo_url,
                ref=git_repo_config.ref,
                include=git_repo_config.include,
                exclude=git_repo_config.exclude,
                subdir=git_repo_config.subdir,
            )
        except ValueError as exc:
            exit_with_cli_error(str(exc), command="git_repo")

        print("Git repo adapter invoked")
        print(f"  repo_url: {git_repo_config.repo_url}")
        print(f"  output_dir: {render_user_path(git_repo_config.output_dir)}")
        requested_ref_label = (
            git_repo_config.ref if git_repo_config.ref is not None else "(default branch)"
        )
        print(f"  requested_ref: {requested_ref_label}")
        if git_repo_config.subdir is not None:
            print(f"  subdir: {git_repo_config.subdir}")
        if git_repo_config.include:
            print(f"  include: {', '.join(git_repo_config.include)}")
        if git_repo_config.exclude:
            print(f"  exclude: {', '.join(git_repo_config.exclude)}")
        print(f"  run_mode: {'dry-run' if git_repo_config.dry_run else 'write'}")

        try:
            previous_manifest_index = load_previous_manifest_index(git_repo_config.output_dir)
        except RuntimeError as exc:
            exit_with_cli_error(str(exc), command="git_repo")

        print("\nPlan: Git repo run")
        print(f"  working_dir: {render_user_path(snapshot.repo_dir)}")
        print(f"  resolved_ref: {snapshot.ref}")
        print(f"  commit_sha: {snapshot.commit_sha}")
        print(f"  tracked_files: {len(snapshot.discovered_paths)}")
        filtered_out_count = len(snapshot.discovered_paths) - len(snapshot.selected_paths)
        print(f"  selected_files: {len(snapshot.selected_paths)}")
        print(f"  filtered_out: {filtered_out_count}")

        manifest_entries: list[dict[str, object]] = []
        written_output_paths: list[Path] = []
        for repo_file in snapshot.files:
            markdown = normalize_to_markdown(
                {
                    "title": repo_file.title,
                    "canonical_id": repo_file.canonical_id,
                    "source_url": repo_file.source_url,
                    "content": repo_file.content,
                    "source": repo_file.source,
                    "adapter": repo_file.adapter,
                }
            )
            output_path = git_repo_markdown_path(git_repo_config.output_dir, repo_file.repo_path)
            manifest_entries.append(
                build_manifest_entry(
                    canonical_id=repo_file.canonical_id,
                    source_url=repo_file.source_url,
                    output_path=output_path,
                    output_dir=git_repo_config.output_dir,
                    title=repo_file.title,
                    content_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                    path=repo_file.repo_path,
                    ref=snapshot.ref,
                    commit_sha=snapshot.commit_sha,
                )
            )
            written_output_paths.append(output_path)
        stale_artifacts = [
            (artifact.canonical_id, artifact.output_path)
            for artifact in find_stale_artifacts(
                git_repo_config.output_dir,
                previous_manifest_index,
                current_output_paths=[str(entry["output_path"]) for entry in manifest_entries],
            )
        ]

        for repo_file, output_path in zip(snapshot.files, written_output_paths, strict=True):
            print(f"\n  path: {repo_file.repo_path}")
            print(f"  Artifact path: {render_user_path(output_path)}")
            content = repo_file.content
            if content:
                print("  content_status: UTF-8 text with content")
            else:
                print(
                    "  content_status: empty UTF-8 file; output will contain metadata "
                    "and an empty content section"
                )
            print(f"  action: {'would write' if git_repo_config.dry_run else 'write'}")

        for skipped_file in snapshot.skipped_files:
            output_path = git_repo_markdown_path(
                git_repo_config.output_dir,
                skipped_file.repo_path,
            )
            print(f"\n  path: {skipped_file.repo_path}")
            print(f"  Artifact path: {render_user_path(output_path)}")
            print(f"  content_status: skipped ({skipped_file.reason})")
            print(f"  action: {'would skip' if git_repo_config.dry_run else 'skip'}")

        manifest_output_path = output_dir / "manifest.json"
        if git_repo_config.dry_run:
            print(
                "\nSummary: would write "
                f"{len(snapshot.files)}, would skip {len(snapshot.skipped_files)}"
            )
            print(f"  stale_artifacts: {len(stale_artifacts)}")
            print_stale_artifacts(git_repo_config.output_dir, stale_artifacts)
            print(f"Manifest path: {render_user_path(manifest_output_path)}")
            print_dry_run_complete()
            return 0

        try:
            for repo_file in snapshot.files:
                markdown = normalize_to_markdown(
                    {
                        "title": repo_file.title,
                        "canonical_id": repo_file.canonical_id,
                        "source_url": repo_file.source_url,
                        "content": repo_file.content,
                        "source": repo_file.source,
                        "adapter": repo_file.adapter,
                    }
                )
                write_git_repo_markdown(
                    git_repo_config.output_dir,
                    repo_file.repo_path,
                    markdown,
                )
            manifest = write_manifest(
                git_repo_config.output_dir,
                manifest_entries,
            )
        except OSError as exc:
            exit_with_output_error(
                git_repo_config.output_dir,
                command="git_repo",
                exc=exc,
            )

        for output_path in written_output_paths:
            print(f"\nWrote: {render_user_path(output_path)}")
        for skipped_file in snapshot.skipped_files:
            print(f"\nSkipped: {skipped_file.repo_path} ({skipped_file.reason})")
        print(f"\nSummary: wrote {len(snapshot.files)}, skipped {len(snapshot.skipped_files)}")
        print(f"  stale_artifacts: {len(stale_artifacts)}")
        print_stale_artifacts(git_repo_config.output_dir, stale_artifacts)
        print(f"Manifest path: {render_user_path(manifest)}")
        print_write_complete(output_dir)
        return 0

    parser.error("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
