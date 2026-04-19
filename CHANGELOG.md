# Changelog

## 0.3.0

- Added manifest-based incremental sync for Confluence so repeated runs can skip rewriting pages that were already written.
- Defined skip eligibility using only matching `canonical_id`, matching `output_path`, and on-disk file existence for the expected artifact.
- Improved recursive dry-run reporting to show both would-write and would-skip counts alongside the planned output paths.
- Updated replacement manifests to include both newly written pages and skipped pages from the current run.
- Added hardening coverage and README guidance for incremental sync, including artifact-based output-directory reuse behavior.

## 0.2.0

- Added recursive Confluence traversal with `--tree` and depth-limited traversal via `--max-depth`.
- Added canonical page ID deduplication so repeated pages are fetched, written, and listed in the manifest once per run.
- Added deterministic recursive ordering with breadth-first traversal by depth and lexical canonical ID ordering within each depth.
- Updated recursive manifests to include `root_page_id` and `max_depth` while keeping per-file entries minimal.
- Improved recursive dry runs with human-readable planning output and a unique page summary such as `5 unique pages`.
- Added recursive contract coverage and synthetic stress tests for deeper, wider, and duplicate-heavy traversal shapes.
