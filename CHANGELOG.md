# Changelog

Confluence release notes below describe shipped CLI wiring, manifest behavior,
design docs, and contract coverage in this repository. The default Confluence
client remains the stub path, while the opt-in real client path now supports
single-page live fetches for Confluence.

Formal changelog coverage begins at `0.2.0`, when this repository started using
`CHANGELOG.md` as part of the release flow. Earlier tagged releases `v0.1.0` and
`v0.1.1` predate that practice and are not backfilled here.

## 0.4.0

- Added opt-in real Confluence client support through `--client-mode real` while
  preserving the existing stub client as the default behavior.
- Shipped v1 single-page live fetches by canonical page ID, returning real page
  title, content, canonical ID, and absolute source URL for the existing
  normalization and write pipeline.
- Added `bearer-env` authentication for real mode via `CONFLUENCE_BEARER_TOKEN`.
- Added fail-fast real-client error handling for missing auth, `401/403` auth
  failures, `404` not-found responses, malformed payloads, URL construction
  failures, and page ID mismatches.
- Added contract coverage for stub-versus-real mode selection and real-client
  mapping behavior, plus hardening coverage for response-shape and source-URL
  edge cases.

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
