"""CLI entrypoint for knowledge_adapters."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


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
        "--auth-method",
        default="bearer-env",
        help="Authentication method identifier.",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "confluence":
        from knowledge_adapters.confluence.client import fetch_page
        from knowledge_adapters.confluence.config import ConfluenceConfig
        from knowledge_adapters.confluence.normalize import normalize_to_markdown
        from knowledge_adapters.confluence.resolve import resolve_target
        from knowledge_adapters.confluence.writer import write_markdown

        confluence_config = ConfluenceConfig(
            base_url=args.base_url,
            target=args.target,
            output_dir=args.output_dir,
            auth_method=args.auth_method,
            dry_run=args.dry_run,
            tree=args.tree,
            max_depth=args.max_depth,
        )

        target = resolve_target(confluence_config.target)

        print("Confluence adapter invoked")
        print(f"  base_url: {confluence_config.base_url}")
        print(f"  target: {target.raw_value}")
        print(f"  output_dir: {confluence_config.output_dir}")
        print(f"  auth_method: {confluence_config.auth_method}")
        print(f"  dry_run: {confluence_config.dry_run}")
        print(f"  tree: {confluence_config.tree}")
        print(f"  max_depth: {confluence_config.max_depth}")

        page = fetch_page(target)
        markdown = normalize_to_markdown(page)

        if confluence_config.dry_run:
            print("\n--- DRY RUN OUTPUT ---\n")
            print(markdown)
            return 0

        page_id = str(page["canonical_id"])
        output_path = write_markdown(confluence_config.output_dir, page_id, markdown)
        print(f"\nWrote: {output_path}")
        return 0

    if args.command == "local_files":
        from pathlib import Path

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

        if local_files_config.dry_run:
            print("\n--- DRY RUN OUTPUT ---\n")
            print(markdown)
            return 0

        input_path = Path(local_files_config.file_path)
        output_name = input_path.stem or input_path.name
        output_path = write_markdown(local_files_config.output_dir, output_name, markdown)
        print(f"\nWrote: {output_path}")
        return 0

    parser.error("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
