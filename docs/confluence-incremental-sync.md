# Confluence Incremental Sync Design

## Purpose

This document defines a minimal v1 incremental sync capability for the Confluence adapter.

The goal is to let repeated runs avoid re-writing page files that were already written in a previous successful non-dry run, while keeping the behavior simple, bounded, and easy to test.

This design extends the current Confluence adapter model without changing the existing `manifest.json` shape or adding any new persistence layer.

## Scope

v1 covers only:

- using the existing per-run `manifest.json` as the source of truth for prior writes
- determining whether a candidate page has already been written in a previous run
- skipping file writes when the prior manifest and current output path agree on the same canonical page ID
- reporting skipped pages in dry-run output and run summaries

v1 does not attempt to detect page updates. It only detects whether the adapter has already written the page artifact that this run would otherwise write.

## Terms

- current run: the Confluence adapter invocation happening now
- previous manifest: the existing `manifest.json` found in the requested output directory before the current run starts
- manifest entry: one object in `manifest.json["files"]`
- canonical page ID: the stable Confluence page identifier used as the page identity key
- candidate page: a page included by the current run after normal resolution, traversal, and deduplication
- already written: a candidate page that matches a prior manifest entry under the rules defined below

## Existing Baseline

The current adapter already defines the pieces this design builds on:

- page files are written to `pages/<canonical_id>.md`
- `manifest.json` is written in the output directory
- the manifest is a per-run artifact, not an append-only history
- dry-run computes planned output paths without writing files
- canonical page ID is already the primary identity key for traversal and output naming

Because output naming is already derived from canonical page ID, incremental sync can stay minimal and avoid title-based or content-based comparisons.

## Source of Truth

The existing `manifest.json` in the selected output directory is the only source of truth for prior writes.

The adapter should:

1. look for `<output-dir>/manifest.json` at the start of a non-dry run and dry run
2. treat that file as the description of the most recent successful write run for that output directory
3. use only its existing `files` entries for incremental comparison

No external database, cache file, sidecar index, timestamp store, or in-file metadata should be introduced.

## What Counts as "Already Written"

A candidate page counts as already written when all of the following are true:

1. a previous `manifest.json` exists and can be parsed successfully
2. the previous manifest contains a `files` entry whose `canonical_id` matches the candidate page's canonical page ID exactly
3. that same manifest entry's `output_path` matches the output path the current run would use for that candidate page
4. the file at `<output-dir>/<output_path>` currently exists on disk

For the current adapter layout, this means a page is already written only when:

- the manifest says the page was previously written as `pages/<canonical_id>.md`
- the current run would also write `pages/<canonical_id>.md`
- that file still exists

All three checks matter:

- canonical page ID confirms page identity
- manifest `output_path` confirms the expected file location
- file existence confirms the manifest is not pointing at a missing artifact

If any of those checks fail, the page is treated as needing a write.

## Comparison Rules

Comparison is intentionally narrow and uses only existing manifest fields.

### Fields used

- `canonical_id`
- `output_path`

### Fields ignored

- `generated_at`
- `source_url`
- `title`
- `root_page_id`
- `max_depth`

These fields may still be useful for reporting, but they must not affect incremental skip eligibility in v1.

### Why this is sufficient for v1

The writer already derives the output path from canonical page ID. Requiring both fields to agree keeps the comparison explicit without changing manifest shape, and file existence prevents a stale manifest from suppressing a needed write.

## Normal Run Behavior

For a normal non-dry run:

1. resolve the target and traverse pages as usual
2. normalize each included page as needed by the existing flow
3. compute the deterministic output path for each candidate page
4. load the previous manifest once, if it exists
5. classify each candidate page as either:
   - `write`: not already written
   - `skip`: already written
6. write markdown files only for `write` pages
7. write a new `manifest.json` for the current run after successful completion

### Manifest output for normal runs

The manifest remains a per-run artifact and is still replaced, not merged.

For v1 incremental sync, the new manifest written after a successful normal run should include:

- every page written during the current run
- every page skipped during the current run because it was already written

This preserves the manifest as the source of truth for the current output directory's expected artifact set, even when some files were reused instead of re-written.

### Summary output for normal runs

The normal run summary should distinguish between:

- pages written in this run
- pages skipped because they were already written

This keeps incremental behavior visible and testable without changing the underlying file format.

## Dry-Run Behavior

Dry run still performs no writes, but it must still compute incremental classifications.

For a dry run:

1. resolve the target and traverse pages as usual
2. compute the deterministic output path for each candidate page
3. load the previous manifest once, if it exists
4. classify each candidate page as either `would write` or `would skip`
5. print the planned action for every included page
6. print a summary that includes both counts

Dry run must not:

- write markdown files
- write or modify `manifest.json`
- create directories solely for output artifacts

### Dry-run reporting requirement

Skipped pages must still appear in dry-run output.

That means dry run should report all included pages, not only the pages that would be newly written. A human reviewing the dry run should be able to see:

- which pages are part of the run
- which of those pages would be written
- which of those pages would be skipped as already written

## Failure Behavior

v1 should keep failure handling simple and follow the existing fail-fast model.

### Missing manifest

If no previous `manifest.json` exists, incremental sync is effectively disabled for that run:

- all candidate pages are treated as `write`
- the run proceeds normally

### Unreadable or invalid manifest

If `manifest.json` exists but cannot be read or parsed, the run should fail before any output files are written.

Rationale:

- the manifest is the declared source of truth
- silently ignoring a malformed manifest could hide state drift
- fail-fast behavior is easier to test than partial fallback rules

Dry run should also fail in this case, because it cannot reliably determine skip eligibility.

### Missing file referenced by manifest

If a manifest entry matches the candidate page by `canonical_id` and `output_path` but the referenced file does not exist, that page is not considered already written.

Behavior:

- treat the page as `write`
- continue the run

This handles cases where the file was manually deleted while the manifest remained behind.

### Mid-run write failure

If a normal run fails while writing one of the required `write` pages:

- stop the run
- do not write a replacement `manifest.json`

This preserves the current fail-fast, no-partial-success-manifest behavior.

## Edge Cases

### Output directory reused for a different target

Reusing the same output directory for a different target is allowed.

In v1, incremental sync is based only on canonical page ID and output path. The system does not track, persist, or validate root target identity.

As a result, reusing an output directory may cause pages to be skipped when the new run includes canonical page IDs that overlap with artifacts already recorded in the existing manifest and still present on disk.

This is expected behavior in v1, not an error condition.

The output directory is treated as a canonical artifact store keyed by canonical page ID. Users are responsible for choosing separate output directories when target-level isolation is required.

### Stale entries for pages not in the current run

Previous manifest entries for pages outside the current run should not influence candidate selection. They only matter if the current run includes a page with the same canonical page ID and output path.

### Duplicate entries in an invalid manifest

If a previous manifest contains multiple `files` entries for the same canonical page ID or output path, that manifest should be treated as invalid and the run should fail.

This keeps the comparison logic deterministic and avoids inventing conflict-resolution rules.

### Dry run with no manifest

Dry run should still list all candidate pages and mark them as `would write`.

### Skipped page contents changed in Confluence

v1 still skips that page if it satisfies the "already written" rule. Detecting source-side content changes is intentionally out of scope.

## Out of Scope

The following are explicitly out of scope for v1:

- hashing page content
- comparing normalized markdown content
- comparing source timestamps, update times, or version counters
- modifying the existing manifest shape
- adding external storage or adapter-specific state files
- append-only run history
- resume checkpoints
- selective deletion of files no longer present in the current run
- reconciling renamed output paths
- distinguishing between "unchanged in source" and "already written locally"
- partial-success manifest writes

## Testable Acceptance Criteria

The implementation guided by this design should support tests that verify at least:

1. With no existing manifest, a run writes all included pages and records them in the new manifest.
2. A page is skipped only when `canonical_id`, `output_path`, and on-disk file existence all agree with the previous manifest.
3. If the previous manifest matches by `canonical_id` but the expected file is missing, the page is written again.
4. Skipped pages still appear in dry-run output.
5. Dry-run summary reports both would-write and would-skip counts.
6. Normal-run summary reports both written and skipped counts.
7. The replacement manifest for a successful normal run includes both newly written pages and skipped pages from the current run.
8. If `manifest.json` is malformed or unreadable, the run fails before writing files.
9. If the previous manifest contains conflicting duplicate file entries, the run fails.
10. Incremental comparison ignores `generated_at`, `source_url`, `title`, `root_page_id`, and `max_depth`.

## Assumptions

- canonical page IDs are stable across repeated runs for the same Confluence content
- the Confluence adapter continues to write files as `pages/<canonical_id>.md`
- `manifest.json` continues to be replaced on each successful normal run
- the current run can inspect the previous manifest before performing any writes
- keeping skip eligibility independent of source content freshness is acceptable for v1
