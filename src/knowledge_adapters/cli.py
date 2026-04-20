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
  CONFLUENCE_BEARER_TOKEN=... knowledge-adapters confluence \\
    --client-mode real \\
    --auth-method bearer-env \\
    --base-url https://example.com/wiki \\
    --target 12345 \\
    --output-dir ./artifacts
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
            "The default stub mode writes scaffolded output without contacting "
            "Confluence. Use --client-mode real for live Confluence fetches."
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
        help="Confluence page URL or page ID.",
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
            "Client behavior: 'stub' writes scaffolded local output with no "
            "network call; 'real' fetches from Confluence using --auth-method. "
            "Defaults to 'stub'."
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
        "--dry-run",
        action="store_true",
        help="Plan actions without writing files.",
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
    )
    local_files_parser.add_argument(
        "--file-path",
        required=True,
        help="Path to a local file to normalize.",
    )
    local_files_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write normalized local artifacts.",
    )
    local_files_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan actions without writing files.",
    )

    return parser


def exit_with_cli_error(message: str) -> None:
    """Exit the CLI with a stable user-facing error message."""
    print(f"knowledge-adapters confluence: error: {message}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "confluence":
        from knowledge_adapters.confluence.client import (
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
            write_manifest,
            write_manifest_with_context,
        )
        from knowledge_adapters.confluence.models import ResolvedTarget
        from knowledge_adapters.confluence.normalize import normalize_to_markdown
        from knowledge_adapters.confluence.resolve import resolve_target
        from knowledge_adapters.confluence.traversal import walk_pages
        from knowledge_adapters.confluence.writer import markdown_path, write_markdown

        confluence_config = ConfluenceConfig(
            base_url=args.base_url,
            target=args.target,
            output_dir=args.output_dir,
            client_mode=args.client_mode,
            auth_method=args.auth_method,
            dry_run=args.dry_run,
            tree=args.tree,
            max_depth=args.max_depth,
        )
        if confluence_config.max_depth < 0:
            exit_with_cli_error("--max-depth must be greater than or equal to 0.")

        target = resolve_target(confluence_config.target)
        if target.page_id is None:
            exit_with_cli_error(
                f"Could not resolve target {target.raw_value!r}. "
                "Expected a Confluence page ID or full Confluence page URL."
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
                    exit_with_cli_error(str(exc))
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
                print("\nDry run: recursive fetch plan")
                print(f"  resolved_root_page_id: {root_page_id}")
                print(f"  tree: {confluence_config.tree}")
                print(f"  max_depth: {confluence_config.max_depth}")
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
            exit_with_cli_error(str(exc))

        _print_confluence_invocation()
        page_id = str(page["canonical_id"])
        output_path = markdown_path(confluence_config.output_dir, page_id)
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
            print(f"\nDry run: would {action} {output_path}\n")
            if action == "write":
                print(normalize_to_markdown(page))
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

        write_manifest(
            confluence_config.output_dir,
            [
                _build_manifest_entry_for_page(page, output_path),
            ],
        )
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

        print("Local files adapter invoked")
        print(f"  file_path: {local_files_config.file_path}")
        print(f"  output_dir: {local_files_config.output_dir}")
        print(f"  dry_run: {local_files_config.dry_run}")

        page = fetch_file(local_files_config.file_path)
        markdown = normalize_to_markdown(page)

        input_path = Path(local_files_config.file_path)
        output_name = input_path.stem or input_path.name
        output_path = write_markdown(
            local_files_config.output_dir,
            output_name,
            markdown,
            dry_run=local_files_config.dry_run,
        )
        if local_files_config.dry_run:
            print(f"\nDry run: would write {output_path}\n")
            print(markdown)
            return 0

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
        print(f"\nWrote: {output_path}")
        return 0

    parser.error("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
