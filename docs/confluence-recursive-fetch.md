# Confluence Recursive Fetch Design

## Purpose

This document defines the v1 behavior for recursive Confluence page traversal.

It is intended to guide implementation and tests for the `knowledge-adapters confluence` command when tree mode is enabled. This document does not authorize broader adapter work beyond the behaviors listed here.

## Scope

v1 covers only:

- traversal starting from a single root page
- depth-limited child-page traversal
- deduplication by canonical page ID
- writing one markdown artifact per fetched page
- writing one per-run `manifest.json`
- `--dry-run` planning behavior for recursive runs

## Terms

- root page: the page identified by `--target` after resolution to a canonical page ID
- canonical page ID: the stable Confluence page identifier used as the primary identity key
- discovered page: a page returned by traversal before deduplication is applied
- fetched page: a page whose content is actually retrieved and normalized after deduplication
- depth: the number of parent-to-child edges between the root page and another page

## CLI Semantics

### Tree mode

- Recursive traversal is active only when `--tree` is set.
- Without `--tree`, the command behaves as a single-page fetch, regardless of any depth flag.

### Depth flag

v1 should use the existing `--max-depth` flag and define it as the maximum descendant depth from the root page.

If `--max-depth` is omitted, the effective value is `0`.

- the root page is always depth `0`
- direct children of the root are depth `1`
- grandchildren are depth `2`

Examples:

- `--tree --max-depth 0`: fetch only the root page
- `--tree --max-depth 1`: fetch the root page and its direct children
- `--tree --max-depth 2`: fetch the root page, children, and grandchildren

Validation rules:

- `--max-depth` must be an integer greater than or equal to `0`
- negative values should be rejected as CLI usage errors

Traversal rules:

- depth is evaluated relative to the root page, not relative to when a page is rediscovered
- a page at depth `N` may be fetched when `N <= max_depth`
- children of a page at depth `max_depth` may be discovered by the source API, but they must not be fetched or written

## Traversal and Deduplication

### Root-first traversal

The traversal should be logically root-first:

1. resolve `--target` to a canonical root page ID
2. fetch the root page
3. enumerate child pages level by level until `max_depth` is reached
4. fetch and normalize each included page once

The implementation may use any internal traversal strategy, but the externally visible behavior must match the depth semantics in this document.

### Deduplication key

Deduplication must be based only on canonical page ID.

- page title must not be used for deduplication
- source URL must not be used for deduplication
- output path must not be used for deduplication

If the same canonical page ID is discovered more than once during a run, it is still treated as one logical page for that run.

### Deduplication behavior

For a given run:

- each canonical page ID is fetched at most once
- each canonical page ID produces at most one output markdown file
- each canonical page ID appears at most once in `manifest.json`

If the same canonical page ID is discovered at multiple depths, the shallower depth wins for inclusion decisions and reporting.

Example:

- if page `12345` is first discovered at depth `1` and later rediscovered at depth `2`, it is treated as depth `1`
- if page `12345` is first discovered at depth `2` and later rediscovered at depth `1`, it is still treated as depth `1` for final reporting

This rule keeps behavior stable even if the underlying source returns overlapping child listings.

## Output Behavior

### Markdown artifacts

For recursive runs, v1 keeps the existing single-page output layout:

- output files are written under `pages/`
- each page is written as `pages/<canonical_id>.md`

The output path is derived from canonical page ID, which aligns with the deduplication key and avoids title-based collisions.

### Overwrite behavior within a run

Within one run:

- the same output path must not be written more than once
- deduplication must happen before writing to disk

This prevents duplicate discovery from causing duplicate writes.

### Ordering

v1 must produce deterministic output ordering for the manifest and any dry-run plan output.

Required ordering:

- pages are ordered breadth-first by depth from the root
- the root page is always first because it is depth `0`
- all depth `1` pages appear before any depth `2` page, and so on
- within the same depth, pages are ordered by canonical page ID in ascending lexical order

This ordering rule is part of the v1 contract so tests can assert exact manifest and dry-run output order for the same discovered page set.

## Manifest Behavior

Recursive runs still write exactly one `manifest.json` file in the output directory.

The manifest remains a per-run artifact, not an append-only history log.

### Manifest location

- manifest path: `<output-dir>/manifest.json`

### Manifest shape

For recursive runs, the manifest adds only two top-level root-run context fields: `root_page_id` and `max_depth`.

Example recursive shape:

```json
{
  "generated_at": "2026-04-18T12:34:56Z",
  "root_page_id": "12345",
  "max_depth": 2,
  "files": [
    {
      "canonical_id": "12345",
      "source_url": "https://example.com/wiki/spaces/ENG/pages/12345",
      "output_path": "pages/12345.md",
      "title": "Team Notes"
    }
  ]
}
```

For multi-page runs:

- `root_page_id` records the resolved canonical page ID for the traversal root
- `max_depth` records the effective maximum depth used for the run
- `files` contains one entry per fetched page in the current run
- entries use the same minimal schema as single-page runs
- `title` is still optional and included only when already available during the run

Other than `root_page_id` and `max_depth`, v1 does not add recursion-specific manifest fields such as:

- traversal depth
- parent/child relationships
- duplicate-discovery counts
- skipped pages
- failure details

### Manifest replacement behavior

For normal non-dry runs:

- `manifest.json` describes only the pages generated by the current run
- if `manifest.json` already exists, it is replaced, not merged

This matches current single-page behavior and keeps the manifest intentionally minimal.

## Dry-Run Behavior

`--dry-run` must plan the recursive fetch without writing files.

For recursive runs, dry-run behavior should include:

- resolve the root target
- traverse pages up to `max_depth`
- apply canonical-ID deduplication
- compute the output path for each included page

`--dry-run` must not:

- create page markdown files
- create or update `manifest.json`
- create output directories only for the sake of writing files or the manifest

### Dry-run output

For v1, dry-run output should be human-readable and specific enough to confirm the planned run.

Minimum required information:

- that the command is a dry run
- the root target or resolved root page ID
- whether tree mode is enabled
- the effective `max_depth`
- one planned output path per included page
- the total number of unique pages that would be written

Dry-run output should reflect post-deduplication results. A page discovered multiple times must appear only once in the reported plan.

v1 does not need a machine-readable dry-run format.

## Failure and Partial-Run Expectations

v1 should stay minimal:

- this document does not define resume behavior
- this document does not define partial-success manifest entries
- this document does not define best-effort continuation after fetch failures

v1 may fail the run on the first unrecoverable traversal or page-fetch error, and that fail-fast behavior is acceptable.

For v1, expected failure behavior is:

- stop processing additional pages after the first unrecoverable traversal or page-fetch error
- return a failure outcome for the run rather than attempting recovery
- do not write or update a partial-success `manifest.json`

Tests should assert explicit fail-fast behavior and manifest absence on failure rather than expecting retry, resume, checkpointing, or continuation semantics.

## Testable Acceptance Criteria

The implementation should support tests that verify at least the following:

1. `--tree --max-depth 0` writes only the root page and a manifest with one file entry.
2. `--tree --max-depth 1` includes direct children but excludes grandchildren.
3. `--tree --max-depth 2` includes grandchildren.
4. Negative `--max-depth` values are rejected.
5. The same canonical page ID discovered multiple times is fetched once, written once, and appears once in the manifest.
6. Deduplication is based on canonical page ID even when titles or URLs differ.
7. Recursive non-dry runs write exactly one `manifest.json` in the output directory.
8. Recursive manifests include `root_page_id` and `max_depth` at the top level.
9. Recursive manifests contain one file entry per unique fetched page from the current run only.
10. Recursive dry runs do not write markdown files, do not write `manifest.json`, and do not create directories solely for those outputs.
11. Recursive dry-run output lists each unique planned output path once and reports the unique page count.
12. Manifest and dry-run ordering follow breadth-first depth order, with canonical page ID lexical ordering within the same depth.
13. Recursive failures are fail-fast and do not write or update a partial-success manifest.

## Out of Scope for v1

The following are explicitly out of scope:

- attachments, comments, and macro-specific traversal rules
- traversal across spaces or across multiple root targets in one command
- incremental sync or `since` filtering
- deletion of previously generated files that are not part of the current run
- manifest fields beyond `root_page_id`, `max_depth`, and per-file entries, including lineage, skipped pages, or failures
- machine-readable dry-run output
- configurable output naming beyond `pages/<canonical_id>.md`
- cycle reporting beyond canonical-ID deduplication
- retry, resume, or checkpoint support for large traversals
