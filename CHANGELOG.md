# Changelog

Confluence release notes below describe shipped CLI wiring, manifest behavior,
design docs, and contract coverage in this repository. The default Confluence
client remains the stub path, while the opt-in real client path now supports
single-page live fetches for Confluence.

Formal changelog coverage begins at `0.2.0`, when this repository started using
`CHANGELOG.md` as part of the release flow. Earlier tagged releases `v0.1.0` and
`v0.1.1` predate that practice and are not backfilled here.

## 0.6.0

This minor release expands config-driven automation and makes live Confluence
runs more production-ready. It adds multi-run orchestration, source-aware
incremental sync, broader TLS support, and clearer operator-facing output and
examples.

### Config-driven runs

- Added config-driven multi-run execution so one runs file can coordinate
  multiple adapter runs.
- Added opt-in continue-on-error behavior for config runs.
- Hardened config-run validation and error reporting so run failures stay
  visible and easier to troubleshoot.

### Confluence improvements

- Added source-aware incremental sync so repeat runs can skip already-recorded
  Confluence artifacts more predictably.
- Added Confluence CA bundle support and TLS configuration parity for
  config-driven runs.
- Plan output now shows active TLS inputs more clearly, and incremental rewrites
  explain why a page is being rewritten.
- Base URL validation fails earlier, reducing avoidable live-run
  misconfiguration.

### CLI and docs

- CLI path rendering is more consistent, improving dry-run and write output
  readability.
- local_files runs now fail fast on artifact collisions instead of risking
  ambiguous output paths.
- Docs and examples now cover release workflow, command contexts, and
  Confluence auth setup more clearly.

## 0.5.1

This patch release makes the CLI easier to understand and more predictable to
use. It focuses on clearer output, better first-run guidance, improved error
messages, and stronger regression coverage.

### CLI output / behavior

- Help output explains the shared adapter flow more clearly.
- Dry-run and write output are more consistent, with clearer plan, summary, and
  completion messages.
- Artifact and manifest paths are shown more explicitly, making it easier to
  confirm what a run will do.
- Output-related errors now give more direct guidance when a path is invalid or
  not writable.

### Confluence improvements

- Confluence runs use clearer wording for target resolution, dry-run plans, and
  summary output.
- Real-client failures are easier to understand, with more actionable messages
  for auth, network, TLS, and not-found cases.
- URL and target validation are clearer and more consistent, which helps catch
  input mistakes earlier.
- Debug output is easier to use when troubleshooting real-client requests.

### local_files improvements

- local_files first-run behavior is explained more clearly in both help text and
  CLI output.
- Missing files, unreadable files, directories, and non-UTF-8 input now fail
  with more helpful guidance.
- Empty UTF-8 files are handled more clearly and reported in a more
  understandable way.
- Write summaries and planned output paths are easier to read.

### test stability

- CLI smoke and regression coverage were tightened around help text, summaries,
  and manifest behavior to catch output drift earlier.
- Real-client and packaging checks were hardened around failure handling, edge
  cases, and release metadata consistency.

### docs/help

- README and built-in help now give clearer first-run guidance for both
  adapters.
- Installation and local setup instructions are easier to scan.
- Confluence docs better explain common usage paths and troubleshooting
  expectations.
- local_files docs are clearer about supported input and expected behavior.

## 0.5.0

- Added opt-in real Confluence tree traversal via `--client-mode real --tree`
  with depth-limited traversal using the existing `--max-depth` flag.
- Shipped deterministic breadth-first traversal for the real client path, with
  lexical canonical page ID ordering within each depth level.
- Added canonical page ID deduplication across real traversal runs so repeated
  child discovery fetches, writes, and lists each page at most once.
- Added fail-fast real traversal behavior so child-list failures, malformed
  child-list payloads, invalid child IDs, and descendant page-fetch failures
  stop the run without partial markdown or manifest writes.
- Added hardened contract coverage for real traversal edge cases, including
  duplicate-heavy child lists, unsorted child discovery input, shallow-depth
  no-extra-fetch cases, and mixed success/failure runs.
- This release does not add pagination, retries/backoff, auth expansion, or
  richer child metadata beyond canonical child page IDs.

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
