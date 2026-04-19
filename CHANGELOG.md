# Changelog

Confluence release notes below describe shipped CLI wiring, manifest behavior,
design docs, and contract coverage in this repository. The default Confluence
client in `src/knowledge_adapters/confluence/client.py` is still a stub and does
not yet perform live network fetches against Confluence.

## 0.3.0

- Added manifest-based incremental sync rules to the Confluence CLI flow so
  repeated runs can skip rewriting artifacts that were already recorded locally.
- Defined skip eligibility using only matching `canonical_id`, matching `output_path`, and on-disk file existence for the expected artifact.
- Improved recursive dry-run reporting to show both would-write and would-skip
  counts alongside the planned output paths in the scaffolded tree-mode flow.
- Updated replacement manifests to include both newly written pages and skipped
  pages from the current run.
- Added hardening coverage and README guidance for incremental sync, including
  artifact-based output-directory reuse behavior.

## 0.2.0

- Added scaffolded recursive Confluence traversal to the CLI with `--tree` and
  depth-limited traversal via `--max-depth`.
- Added canonical page ID deduplication so repeated pages in tree-mode flows are
  fetched, written, and listed in the manifest once per run.
- Added deterministic recursive ordering with breadth-first traversal by depth
  and lexical canonical ID ordering within each depth.
- Updated tree-mode manifests to include `root_page_id` and `max_depth` while
  keeping per-file entries minimal.
- Improved recursive dry runs with human-readable planning output and a unique
  page summary such as `5 unique pages`.
- Added recursive contract coverage and synthetic stress tests for deeper,
  wider, and duplicate-heavy traversal shapes.
