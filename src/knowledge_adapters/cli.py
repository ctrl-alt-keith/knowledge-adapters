"""CLI entrypoint for knowledge_adapters."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from knowledge_adapters.confluence.auth import SUPPORTED_AUTH_METHODS

CONFLUENCE_HELP_EXAMPLES = """Examples:
  knowledge-adapters confluence \\
    --base-url https://example.com/wiki \\
    --target 12345 \\
    --output-dir ./artifacts
  knowledge-adapters confluence \\
    --base-url https://example.com/wiki \\
    --target https://example.com/wiki/spaces/ENG/pages/12345/Runbook \\
    --output-dir ./artifacts \\
    --dry-run
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
    --output-dir ./artifacts
  knowledge-adapters local_files \\
    --file-path ./notes/today.txt \\
    --output-dir ./artifacts \\
    --dry-run
"""


def _parse_confluence_auth_method(value: str) -> str:
    """Parse and validate a supported Confluence auth method."""
    normalized_value = value.strip()
    if normalized_value in SUPPORTED_AUTH_METHODS:
        return normalized_value

    supported_values = " or ".join(repr(method) for method in SUPPORTED_AUTH_METHODS)
    raise argparse.ArgumentTypeError(f"unsupported value {value!r}. Choose {supported_values}.")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="knowledge-adapters",
        description="Acquire and normalize knowledge sources into local artifacts.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    confluence_parser = subparsers.add_parser(
        "confluence",
        help="Run the Confluence adapter.",
        description=(
            "Normalize a Confluence page or page tree into local markdown artifacts. "
            "Both stub and real modes follow the same target resolution, plan, and "
            "artifact flow. Use --dry-run to preview the same page and manifest plan "
            "a write "
            "run would use. The default stub mode writes scaffolded output without "
            "contacting Confluence. Use --client-mode real for contract-tested live "
            "Confluence fetches."
        ),
        epilog=CONFLUENCE_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    confluence_parser.add_argument(
        "--base-url",
        required=True,
        help="Base Confluence URL, provided at runtime.",
    )
    confluence_parser.add_argument(
        "--target",
        required=True,
        help=(
            "Confluence page ID or full page URL under --base-url. Full URLs are "
            "validated and normalized to canonical pageId form for output and "
            "manifests."
        ),
    )
    confluence_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write normalized local artifacts.",
    )
    confluence_parser.add_argument(
        "--client-mode",
        choices=("stub", "real"),
        default="stub",
        help=(
            "Client behavior: 'stub' uses scaffolded page content with no network "
            "call; 'real' fetches from Confluence using --auth-method. Both modes "
            "resolve --target and write the same local artifact paths. Defaults to "
            "'stub'."
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
        help="Plan the resolved page, output path, and manifest without writing files.",
    )
    confluence_parser.add_argument(
        "--tree",
        action="store_true",
        help="Fetch a page tree instead of a single page.",
    )
    confluence_parser.add_argument(
        "--max-depth",
        type=int,
        default=0,
        help="Maximum recursion depth for tree mode. 0 means single page only.",
    )

    local_files_parser = subparsers.add_parser(
        "local_files",
        help="Run the local files adapter.",
        description=(
            "Normalize a single local UTF-8 text file into a markdown artifact. "
            "Writes pages/<file-stem>.md and manifest.json under --output-dir."
        ),
        epilog=LOCAL_FILES_HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    local_files_parser.add_argument(
        "--file-path",
        required=True,
        metavar="FILE",
        help="Readable UTF-8 text file to normalize.",
    )
    local_files_parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="Directory for generated artifacts: pages/<name>.md and manifest.json.",
    )
    local_files_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned output path and normalized markdown without writing files.",
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

        def _print_confluence_invocation() -> None:
            print("Confluence adapter invoked")
            print(f"  base_url: {confluence_config.base_url}")
            print(f"  target: {target.raw_value}")
            print(f"  output_dir: {confluence_config.output_dir}")
            print(f"  client_mode: {confluence_config.client_mode}")
            print(f"  auth_method: {confluence_config.auth_method}")
            print(f"  dry_run: {confluence_config.dry_run}")
            print(f"  tree: {confluence_config.tree}")
            print(f"  max_depth: {confluence_config.max_depth}")

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

        def _print_single_page_dry_run(
            *,
            page_id: str,
            source_url: str,
            output_path: Path,
            manifest_output_path: Path,
            action: str,
            markdown: str | None = None,
        ) -> None:
            write_count = 1 if action == "write" else 0
            skip_count = 1 if action == "skip" else 0
            print("\nDry run: Confluence page plan")
            print(f"  resolved_page_id: {page_id}")
            print(f"  source_url: {source_url}")
            print(f"  output_path: {output_path}")
            print(f"  manifest_path: {manifest_output_path}")
            print(f"  action: would {action}")
            print(f"  Summary: would write {write_count}, would skip {skip_count}")
            if markdown is not None:
                print()
                print(markdown)

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

            if confluence_config.dry_run:
                manifest_output_path = manifest_path(confluence_config.output_dir)
                print("\nDry run: recursive fetch plan")
                print(f"  resolved_root_page_id: {root_page_id}")
                print(f"  tree: {confluence_config.tree}")
                print(f"  max_depth: {confluence_config.max_depth}")
                print(f"  manifest_path: {manifest_output_path}")
                for _page, output_path, action in page_records:
                    print(f"  would {action} {output_path}")
                print(f"  Summary: would write {write_count}, would skip {skip_count}")
                print(f"  {len(page_records)} unique pages")
                return 0

            files = [
                _build_manifest_entry_for_page(page, output_path)
                for page, output_path, _action in page_records
            ]

            for page, output_path, action in page_records:
                if action == "skip":
                    print(f"\nSkipped: {output_path}")
                    continue

                markdown = normalize_to_markdown(page)
                write_markdown(
                    confluence_config.output_dir,
                    str(page.get("canonical_id") or ""),
                    markdown,
                )
                print(f"\nWrote: {output_path}")

            manifest = write_manifest_with_context(
                confluence_config.output_dir,
                files,
                root_page_id=root_page_id,
                max_depth=confluence_config.max_depth,
            )
            print(f"\nSummary: wrote {write_count}, skipped {skip_count}")
            print(f"\nManifest: {manifest}")
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
            _print_single_page_dry_run(
                page_id=page_id,
                source_url=str(page.get("source_url", "")),
                output_path=output_path,
                manifest_output_path=manifest_output_path,
                action=action,
                markdown=planned_markdown,
            )
            return 0

        if action == "write":
            markdown = normalize_to_markdown(page)
            write_markdown(
                confluence_config.output_dir,
                page_id,
                markdown,
            )
            print(f"\nWrote: {output_path}")
        else:
            print(f"\nSkipped: {output_path}")

        manifest = write_manifest(
            confluence_config.output_dir,
            [
                _build_manifest_entry_for_page(page, output_path),
            ],
        )
        write_count = 1 if action == "write" else 0
        skip_count = 1 if action == "skip" else 0
        print(f"\nSummary: wrote {write_count}, skipped {skip_count}")
        print(f"Manifest: {manifest}")
        return 0

    if args.command == "local_files":
        from pathlib import Path

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

        output_dir = Path(local_files_config.output_dir).expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            exit_with_cli_error(
                (
                    f"Output path is not a directory: {output_dir}. "
                    "Choose a directory path for --output-dir."
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
        print(f"  dry_run: {local_files_config.dry_run}")

        input_path = Path(local_files_config.file_path)
        output_name = input_path.stem or input_path.name
        try:
            output_path = write_markdown(
                local_files_config.output_dir,
                output_name,
                markdown,
                dry_run=local_files_config.dry_run,
            )
        except PermissionError:
            exit_with_cli_error(
                (
                    f"Output directory is not writable: {output_dir}. "
                    "Check the path and permissions for --output-dir."
                ),
                command="local_files",
            )
        except NotADirectoryError:
            exit_with_cli_error(
                (
                    f"Output path is not a directory: {output_dir}. "
                    "Choose a directory path for --output-dir."
                ),
                command="local_files",
            )
        except OSError:
            exit_with_cli_error(
                (
                    f"Could not write output under {output_dir}. "
                    "Check --output-dir and try again."
                ),
                command="local_files",
            )
        if local_files_config.dry_run:
            print(f"\nDry run: would write {output_path}\n")
            print(markdown)
            return 0

        try:
            write_manifest(
                local_files_config.output_dir,
                [
                    build_manifest_entry(
                        canonical_id=str(page["canonical_id"]),
                        source_url=str(page.get("source_url", "")),
                        output_path=output_path,
                        output_dir=local_files_config.output_dir,
                        title=str(page["title"]) if page.get("title") else None,
                    )
                ],
            )
        except PermissionError:
            exit_with_cli_error(
                (
                    f"Output directory is not writable: {output_dir}. "
                    "Check the path and permissions for --output-dir."
                ),
                command="local_files",
            )
        except NotADirectoryError:
            exit_with_cli_error(
                (
                    f"Output path is not a directory: {output_dir}. "
                    "Choose a directory path for --output-dir."
                ),
                command="local_files",
            )
        except OSError:
            exit_with_cli_error(
                (
                    f"Could not write output under {output_dir}. "
                    "Check --output-dir and try again."
                ),
                command="local_files",
            )
        print(f"\nWrote: {output_path}")
        return 0

    parser.error("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
