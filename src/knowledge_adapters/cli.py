"""CLI entrypoint for knowledge_adapters."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from knowledge_adapters.confluence.auth import SUPPORTED_AUTH_METHODS

TOP_LEVEL_HELP_EXAMPLES = """First steps:
  knowledge-adapters --help
  knowledge-adapters local_files --help
  knowledge-adapters confluence --help

Typical flow:
  1. Start with local_files to try the artifact layout with a text file you
     already have.
  2. Start with --dry-run to preview the source, artifact path, manifest path,
     and action.
  3. Re-run without --dry-run to write the same artifact layout under
     ./artifacts.
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


def _parse_confluence_auth_method(value: str) -> str:
    """Parse and validate a supported Confluence auth method."""
    normalized_value = value.strip()
    if normalized_value in SUPPORTED_AUTH_METHODS:
        return normalized_value

    supported_values = " or ".join(repr(method) for method in SUPPORTED_AUTH_METHODS)
    raise argparse.ArgumentTypeError(f"unsupported value {value!r}. Choose {supported_values}.")


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

    return parser


def exit_with_cli_error(
    message: str,
    *,
    command: str,
    debug_lines: Sequence[str] | None = None,
) -> None:
    """Exit the CLI with a stable user-facing error message."""
    print(f"knowledge-adapters {command}: error: {message}", file=sys.stderr)
    if debug_lines:
        for line in debug_lines:
            print(f"  {line}", file=sys.stderr)
    raise SystemExit(2)


def print_dry_run_complete() -> None:
    """Print a consistent dry-run completion message."""
    print("\nDry run complete. No files written.")


def print_write_complete(output_dir: Path) -> None:
    """Print a consistent write completion message."""
    print(f"\nWrite complete. Artifacts created under {output_dir}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "confluence":
        from knowledge_adapters.confluence.client import (
            ConfluenceRequestError,
            fetch_page,
            fetch_real_page,
            list_real_child_page_ids,
        )
        from knowledge_adapters.confluence.config import ConfluenceConfig
        from knowledge_adapters.confluence.incremental import (
            is_already_written,
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
        selected_list_child_page_ids: Callable[[ResolvedTarget], list[str]] | None = None
        if confluence_config.client_mode == "real":

            def selected_fetch_page(resolved_target: ResolvedTarget) -> dict[str, object]:
                return fetch_real_page(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                )

            def selected_list_child_page_ids(
                resolved_target: ResolvedTarget,
            ) -> list[str]:
                return list_real_child_page_ids(
                    resolved_target,
                    base_url=confluence_config.base_url,
                    auth_method=confluence_config.auth_method,
                )
        else:
            selected_fetch_page = fetch_page

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
            print(f"  output_dir: {confluence_config.output_dir}")
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
                print(f"  auth_method: {confluence_config.auth_method}")

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
        ) -> dict[str, str]:
            return build_manifest_entry(
                canonical_id=str(page.get("canonical_id") or ""),
                source_url=str(page.get("source_url", "")),
                output_path=output_path,
                output_dir=confluence_config.output_dir,
                title=str(page["title"]) if page.get("title") else None,
            )

        def _display_output_path(path: Path) -> Path:
            """Return an absolute path for user-facing output."""
            try:
                relative_path = path.relative_to(output_dir_input)
            except ValueError:
                return path if path.is_absolute() else path.resolve()
            return output_dir / relative_path

        def _print_single_page_plan(
            *,
            page_id: str,
            source_url: str,
            output_path: Path,
            manifest_output_path: Path,
            action: str,
            dry_run: bool,
            markdown: str | None = None,
        ) -> None:
            print("\nPlan: Confluence run")
            print(f"  resolved_page_id: {page_id}")
            print(f"  source_url: {source_url}")
            print(f"  Artifact: {_display_output_path(output_path)}")
            print(f"  Manifest: {_display_output_path(manifest_output_path)}")
            print(f"  action: {'would ' if dry_run else ''}{action}")
            if dry_run:
                write_count = 1 if action == "write" else 0
                skip_count = 1 if action == "skip" else 0
                _print_confluence_dry_run_summary(
                    mode="single",
                    total_pages=1,
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
            write_count: int,
            skip_count: int,
        ) -> None:
            descendant_count = max(total_pages - 1, 0)
            summary_lines = (
                f"    mode: {mode}",
                "    pages_in_plan: "
                f"{total_pages} (root 1, descendants {descendant_count})",
                f"    would_write: {write_count}",
                f"    would_skip: {skip_count}",
            )
            print("  Summary:")
            for line in summary_lines:
                print(line)

        if confluence_config.tree:
            if confluence_config.client_mode == "real":
                try:
                    root_page_id, pages = walk_pages(
                        target,
                        max_depth=confluence_config.max_depth,
                        fetch_page=selected_fetch_page,
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
                    fetch_page=selected_fetch_page,
                    list_child_page_ids=selected_list_child_page_ids,
                )
            _print_confluence_invocation()
            previous_manifest_index = load_previous_manifest_index(confluence_config.output_dir)
            page_records: list[tuple[dict[str, object], Path, str]] = []
            for page in pages:
                canonical_id = str(page.get("canonical_id") or "")
                output_path = markdown_path(confluence_config.output_dir, canonical_id)
                action = (
                    "skip"
                    if is_already_written(
                        confluence_config.output_dir,
                        previous_manifest_index,
                        canonical_id=canonical_id,
                        output_path=output_path,
                    )
                    else "write"
                )
                page_records.append((page, output_path, action))

            write_count = sum(
                1 for _page, _output_path, action in page_records if action == "write"
            )
            skip_count = len(page_records) - write_count
            manifest_output_path = manifest_path(confluence_config.output_dir)

            print("\nPlan: Confluence run")
            print(f"  resolved_root_page_id: {root_page_id} (root page)")
            print(f"  max_depth: {confluence_config.max_depth}")
            print(f"  Manifest: {_display_output_path(manifest_output_path)}")
            print(f"  pages_in_tree: {len(page_records)} (root + descendants)")

            if confluence_config.dry_run:
                _print_confluence_dry_run_summary(
                    mode="tree",
                    total_pages=len(page_records),
                    write_count=write_count,
                    skip_count=skip_count,
                )
                for _page, output_path, action in page_records:
                    print(f"  would {action} {_display_output_path(output_path)}")
                print_dry_run_complete()
                return 0

            files = [
                _build_manifest_entry_for_page(page, output_path)
                for page, output_path, _action in page_records
            ]

            try:
                for page, output_path, action in page_records:
                    if action == "skip":
                        print(f"\nSkipped: {_display_output_path(output_path)}")
                        continue

                    markdown = normalize_to_markdown(page)
                    write_markdown(
                        confluence_config.output_dir,
                        str(page.get("canonical_id") or ""),
                        markdown,
                    )
                    print(f"\nWrote: {_display_output_path(output_path)}")

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
            print(f"\nSummary: wrote {write_count}, skipped {skip_count}")
            print(f"Manifest: {_display_output_path(manifest)}")
            print_write_complete(output_dir)
            return 0

        try:
            page = selected_fetch_page(target)
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
        previous_manifest_index = load_previous_manifest_index(confluence_config.output_dir)
        action = (
            "skip"
            if is_already_written(
                confluence_config.output_dir,
                previous_manifest_index,
                canonical_id=page_id,
                output_path=output_path,
            )
            else "write"
        )

        if confluence_config.dry_run:
            planned_markdown = normalize_to_markdown(page) if action == "write" else None
            _print_single_page_plan(
                page_id=page_id,
                source_url=str(page.get("source_url", "")),
                output_path=output_path,
                manifest_output_path=manifest_output_path,
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
            action=action,
            dry_run=False,
        )

        try:
            if action == "write":
                markdown = normalize_to_markdown(page)
                write_markdown(
                    confluence_config.output_dir,
                    page_id,
                    markdown,
                )
                print(f"\nWrote: {_display_output_path(output_path)}")
            else:
                print(f"\nSkipped: {_display_output_path(output_path)}")

            manifest = write_manifest(
                confluence_config.output_dir,
                [
                    _build_manifest_entry_for_page(page, output_path),
                ],
            )
        except OSError as exc:
            exit_with_output_error(
                confluence_config.output_dir,
                command="confluence",
                exc=exc,
            )
        write_count = 1 if action == "write" else 0
        skip_count = 1 if action == "skip" else 0
        print(f"\nSummary: wrote {write_count}, skipped {skip_count}")
        print(f"Manifest: {_display_output_path(manifest)}")
        print_write_complete(output_dir)
        return 0

    if args.command == "local_files":
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
        print(f"  file_path: {local_files_config.file_path}")
        print(f"  output_dir: {local_files_config.output_dir}")
        print(f"  run_mode: {'dry-run' if local_files_config.dry_run else 'write'}")

        input_path = Path(local_files_config.file_path)
        output_name = input_path.stem or input_path.name
        resolved_input_path = input_path.resolve()
        manifest_output_path = output_dir / "manifest.json"
        output_path = output_dir / "pages" / f"{output_name}.md"
        manifest_entry_output_path = output_dir_input / "pages" / f"{output_name}.md"

        print("\nPlan: Local files run")
        print(f"  resolved_file_path: {resolved_input_path}")
        print(f"  source_url: {page.get('source_url', '')}")
        print(f"  Artifact: {output_path}")
        print(f"  Manifest: {manifest_output_path}")
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
        print(f"\nWrote: {output_path}")
        print("\nSummary: wrote 1, skipped 0")
        print(f"Artifact: {output_path}")
        print(f"Manifest: {output_dir / manifest.relative_to(output_dir_input)}")
        print_write_complete(output_dir)
        return 0

    parser.error("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
