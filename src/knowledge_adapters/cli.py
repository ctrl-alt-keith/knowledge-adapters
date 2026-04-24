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

from knowledge_adapters.confluence.auth import SUPPORTED_AUTH_METHODS, resolve_tls_inputs

TOP_LEVEL_HELP_EXAMPLES = """First steps:
  knowledge-adapters --help
  knowledge-adapters run runs.yaml
  knowledge-adapters local_files --help
  knowledge-adapters confluence --help

Typical flow:
  1. Start with local_files to try the artifact layout with a text file you
     already have.
  2. Start with --dry-run to preview the source, artifact path, manifest path,
     and action.
  3. Re-run without --dry-run to write the same artifact layout under
     ./artifacts.
  4. Use knowledge-adapters run runs.yaml to refresh multiple sources in order.
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

RUN_HELP_EXAMPLES = """Examples:
  knowledge-adapters run runs.yaml
  knowledge-adapters run ./configs/runs.yaml
  knowledge-adapters run runs.yaml --only team-notes,docs-home
  knowledge-adapters run runs.yaml --continue-on-error
"""

_WRITE_SUMMARY_RE = re.compile(r"Summary: wrote (?P<wrote>\d+), skipped (?P<skipped>\d+)")
_DRY_RUN_SUMMARY_RE = re.compile(
    r"Summary: would write (?P<wrote>\d+), would skip (?P<skipped>\d+)"
)
_DRY_RUN_BLOCK_WRITE_RE = re.compile(r"would_write: (?P<wrote>\d+)")
_DRY_RUN_BLOCK_SKIP_RE = re.compile(r"would_skip: (?P<skipped>\d+)")
_CLI_ERROR_RE = re.compile(r"^knowledge-adapters (?P<command>\S+): error: (?P<message>.+)$")


@dataclass(frozen=True)
class MultiRunSummary:
    """Summary parsed from one adapter CLI execution."""

    dry_run: bool
    wrote: int
    skipped: int


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
        raise argparse.ArgumentTypeError(
            "expected one or more comma-separated run names."
        )

    return tuple(parsed_names)


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
        (
            f"Could not write output under {resolved_output_dir}. "
            "Verify --output-dir and try again."
        ),
        command=command,
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
            "Base Confluence URL for validating full page URLs and building "
            "canonical source URLs."
        ),
    )
    confluence_parser.add_argument(
        "--target",
        required=True,
        help=(
            "Confluence page ID or full page URL under --base-url. The CLI resolves "
            "either input into one canonical page ID and source URL for artifact "
            "and manifest reporting."
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        from knowledge_adapters.run_config import load_run_config, select_runs

        try:
            run_config = load_run_config(args.config_path)
            selected_runs = select_runs(run_config, only_names=args.only)
        except ValueError as exc:
            exit_with_cli_error(str(exc), command="run")

        skipped_disabled_runs = (
            ()
            if args.only is not None
            else tuple(
                configured_run
                for configured_run in run_config.runs
                if not configured_run.enabled
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
        write_runs = 0
        dry_run_runs = 0
        total_wrote = 0
        total_skipped = 0
        total_would_write = 0
        total_would_skip = 0

        for index, configured_run in enumerate(selected_runs, start=1):
            display_command = shlex.join(("knowledge-adapters", *configured_run.argv))
            print(
                f"\nRun {index}/{len(selected_runs)}: "
                f"{configured_run.name} ({configured_run.run_type})"
            )
            print(f"  command: {display_command}")

            captured_stdout = io.StringIO()
            captured_stderr = io.StringIO()
            try:
                with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
                    exit_code = main(configured_run.argv)
            except SystemExit:
                output = captured_stdout.getvalue()
                if output:
                    print(output, end="" if output.endswith("\n") else "\n")
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
            if output:
                print(output, end="" if output.endswith("\n") else "\n")

            try:
                summary = _parse_multi_run_summary(output)
            except RuntimeError as exc:
                exit_with_cli_error(str(exc), command="run")

            completed_runs += 1
            if summary.dry_run:
                dry_run_runs += 1
                total_would_write += summary.wrote
                total_would_skip += summary.skipped
                print(
                    f"Run summary: would write {summary.wrote}, "
                    f"would skip {summary.skipped}"
                )
            else:
                write_runs += 1
                total_wrote += summary.wrote
                total_skipped += summary.skipped
                print(f"Run summary: wrote {summary.wrote}, skipped {summary.skipped}")

        print("\nAggregate summary:")
        print(f"  runs_completed: {completed_runs}")
        print(f"  runs_failed: {failed_runs}")
        print(f"  runs_skipped_disabled: {len(skipped_disabled_runs)}")
        print(f"  write_runs: {write_runs}")
        print(f"  dry_run_runs: {dry_run_runs}")
        print(f"  wrote: {total_wrote}")
        print(f"  skipped: {total_skipped}")
        if dry_run_runs > 0:
            print(f"  would_write: {total_would_write}")
            print(f"  would_skip: {total_would_skip}")
        if failed_runs > 0:
            print(
                "Config run completed with failures. "
                f"Processed {completed_runs} successful run(s) and {failed_runs} failed "
                f"run(s) from {render_user_path(run_config.config_path)}"
            )
            return 1

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
        )
        from knowledge_adapters.confluence.config import ConfluenceConfig
        from knowledge_adapters.confluence.incremental import (
            PageSyncDecision,
            classify_page_sync,
            load_previous_manifest_index,
        )
        from knowledge_adapters.confluence.manifest import (
            build_manifest_entry,
            manifest_path,
            write_manifest,
            write_manifest_with_context,
        )
        from knowledge_adapters.confluence.models import ResolvedTarget
        from knowledge_adapters.confluence.normalize import normalize_to_markdown
        from knowledge_adapters.confluence.resolve import resolve_target_for_base_url
        from knowledge_adapters.confluence.traversal import walk_pages
        from knowledge_adapters.confluence.writer import markdown_path, write_markdown

        confluence_config = ConfluenceConfig(
            base_url=args.base_url,
            target=args.target,
            output_dir=args.output_dir,
            ca_bundle=args.ca_bundle,
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

        try:
            target = resolve_target_for_base_url(
                confluence_config.target,
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
        if confluence_config.client_mode == "real":

            def selected_fetch_page(resolved_target: ResolvedTarget) -> dict[str, object]:
                return fetch_real_page(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                    ca_bundle=confluence_config.ca_bundle,
                    client_cert_file=confluence_config.client_cert_file,
                    client_key_file=confluence_config.client_key_file,
                )

            def selected_fetch_page_summary(
                resolved_target: ResolvedTarget,
            ) -> dict[str, object]:
                return fetch_real_page_summary(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                    ca_bundle=confluence_config.ca_bundle,
                    client_cert_file=confluence_config.client_cert_file,
                    client_key_file=confluence_config.client_key_file,
                )

            def selected_list_child_page_ids(
                resolved_target: ResolvedTarget,
            ) -> list[str]:
                return list_real_child_page_ids(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                    ca_bundle=confluence_config.ca_bundle,
                    client_cert_file=confluence_config.client_cert_file,
                    client_key_file=confluence_config.client_key_file,
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
            content_source = (
                "scaffolded page content"
                if confluence_config.client_mode == "stub"
                else "live Confluence content"
            )
            run_mode = "dry-run" if confluence_config.dry_run else "write"
            print("Confluence adapter invoked")
            print(f"  base_url: {confluence_config.base_url}")
            print(f"  target: {target.raw_value}")
            print(f"  output_dir: {render_user_path(confluence_config.output_dir)}")
            print(f"  client_mode: {confluence_config.client_mode}")
            print(f"  content_source: {content_source}")
            if confluence_config.dry_run:
                mode = "tree" if confluence_config.tree else "single"
                print(f"  mode: {mode}")
            else:
                fetch_scope = "tree" if confluence_config.tree else "page"
                print(f"  fetch_scope: {fetch_scope}")
            print(f"  run_mode: {run_mode}")
            if confluence_config.tree:
                max_depth = str(confluence_config.max_depth)
                if confluence_config.dry_run:
                    max_depth = f"{max_depth} ({_describe_tree_depth(confluence_config.max_depth)})"
                print(f"  max_depth: {max_depth}")
            if confluence_config.client_mode == "real":
                resolved_tls_inputs = resolve_tls_inputs(
                    ca_bundle=confluence_config.ca_bundle,
                    client_cert_file=confluence_config.client_cert_file,
                    client_key_file=confluence_config.client_key_file,
                )
                tls_inputs: list[str] = []
                if resolved_tls_inputs.ca_bundle:
                    tls_inputs.append(
                        f"ca_bundle={render_user_path(resolved_tls_inputs.ca_bundle)}"
                    )
                if resolved_tls_inputs.client_cert_file:
                    tls_inputs.append(
                        "client_cert_file="
                        f"{render_user_path(resolved_tls_inputs.client_cert_file)}"
                    )
                if resolved_tls_inputs.client_key_file:
                    tls_inputs.append(
                        "client_key_file="
                        f"{render_user_path(resolved_tls_inputs.client_key_file)}"
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
                last_modified=(
                    str(page["last_modified"]) if page.get("last_modified") else None
                ),
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
        ) -> None:
            descendant_count = max(total_pages - 1, 0)
            summary_lines = (
                f"    mode: {mode}",
                "    pages_in_plan: "
                f"{total_pages} (root 1, descendants {descendant_count})",
                f"    new_pages: {new_count}",
                f"    changed_pages: {changed_count}",
                f"    unchanged_pages: {unchanged_count}",
                f"    would_write: {write_count}",
                f"    would_skip: {skip_count}",
            )
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
        ) -> None:
            print(f"\nSummary: wrote {write_count}, skipped {skip_count}")
            print(f"  new_pages: {new_count}")
            print(f"  changed_pages: {changed_count}")
            print(f"  unchanged_pages: {unchanged_count}")
            print(f"  pages_written: {write_count}")
            print(f"  pages_skipped: {skip_count}")

        def _print_stub_tree_mode_note() -> None:
            if not (confluence_config.tree and confluence_config.client_mode == "stub"):
                return

            print(
                "  note: stub mode does not support descendant discovery; "
                "use --client-mode real to discover descendants from Confluence."
            )

        if confluence_config.tree:
            previous_manifest_index = load_previous_manifest_index(confluence_config.output_dir)
            tree_fetch_page = (
                selected_fetch_page
                if previous_manifest_index is None
                else selected_fetch_page_summary
            )
            if confluence_config.client_mode == "real":
                try:
                    root_page_id, pages = walk_pages(
                        target,
                        max_depth=confluence_config.max_depth,
                        fetch_page=tree_fetch_page,
                        list_child_page_ids=selected_list_child_page_ids,
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
                )
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
            )
            print(f"Manifest: {_display_output_path(manifest)}")
            print_write_complete(output_dir)
            return 0

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
                markdown=planned_markdown,
            )
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
        )
        print(f"Manifest: {_display_output_path(manifest)}")
        print_write_complete(output_dir)
        return 0

    if args.command == "local_files":
        from knowledge_adapters.confluence.incremental import (
            load_previous_manifest_output_index,
        )
        from knowledge_adapters.confluence.manifest import (
            build_manifest_entry,
            write_manifest,
        )
        from knowledge_adapters.local_files.client import fetch_file
        from knowledge_adapters.local_files.config import LocalFilesConfig
        from knowledge_adapters.local_files.normalize import normalize_to_markdown
        from knowledge_adapters.local_files.writer import write_markdown

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
        print(f"Artifact path: {render_user_path(output_path)}")
        print(f"Manifest path: {render_user_path(manifest)}")
        print_write_complete(output_dir)
        return 0

    parser.error("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
