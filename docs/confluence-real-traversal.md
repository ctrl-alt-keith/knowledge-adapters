# Confluence Real Traversal Design

## Purpose

This document defines a minimal v1 design for enabling real child-page traversal when `knowledge-adapters confluence` runs with `--client-mode real`.

Today, the shipped implementation still rejects `--client-mode real` together with real tree traversal. This document defines the next minimal phase for lifting that restriction.

The goal is to turn the existing scaffolded tree mode into real behavior for the opt-in real client path without expanding scope beyond what is required for:

- child-page discovery
- depth-limited traversal via `--max-depth`
- canonical page ID deduplication

This design builds on the existing real client contract in [docs/confluence-real-client.md](/Users/keith/src/ctrl-alt-keith/knowledge-adapters/docs/confluence-real-client.md) and the existing traversal contract in [docs/confluence-recursive-fetch.md](/Users/keith/src/ctrl-alt-keith/knowledge-adapters/docs/confluence-recursive-fetch.md).

## v1 Scope

v1 includes only:

- keeping `--client-mode real` as an explicit opt-in mode
- using the existing real page-fetch path for root and descendant page content fetches
- adding real child-page discovery by canonical page ID
- using the existing `--tree` and `--max-depth` CLI semantics for real traversal
- deterministic breadth-first traversal outside the client
- canonical page ID deduplication across the full run
- fail-fast behavior on the first unrecoverable traversal or fetch error

v1 does not broaden auth, manifest, writer, or incremental-sync scope.

## Design Summary

The real traversal path should keep the current split between data access and traversal policy:

- the real client fetches one page and lists one page's direct child page IDs
- the traversal layer decides depth handling, queueing, ordering, deduplication, and stopping conditions
- the writer, manifest, and incremental-sync layers continue to consume the same ordered page payloads they already expect

This means real tree mode should reuse the existing live page fetch path and add only one new real-client capability: child-ID discovery for a single parent page.

## Client Responsibilities

### Existing responsibility

The existing real client responsibility remains unchanged:

- fetch one Confluence page by canonical page ID
- validate the source response
- map it into the adapter page payload

### New v1 traversal responsibility

To support traversal, the real client should add one minimal surface:

- list the direct child page IDs for one canonical parent page ID

For v1, child discovery should return:

- `list[str]`
- one canonical child page ID per entry
- only the data required for traversal

It should not return traversal metadata such as:

- depth
- parent chains
- sibling order policy
- titles
- URLs
- timestamps
- attachment/comment metadata

The client is responsible for:

- making the child-list request
- validating the source child-list response shape
- extracting canonical child page IDs from that response

The client is not responsible for:

- recursion
- `--max-depth` enforcement
- breadth-first vs. depth-first policy
- deduplication across the run
- final output ordering

### Why child discovery is separate from page fetch

The real client should not collapse traversal into `fetch_real_page`.

Keeping child discovery separate preserves the existing boundary:

- `fetch_real_page(...)` returns one page payload
- `list_real_child_page_ids(...)` returns the direct child IDs for one page

That keeps the client focused on fetching and mapping source data, while traversal stays in the traversal layer where tree policy already belongs.

## Traversal Responsibilities

The traversal layer should orchestrate the run using injected data-access callables rather than embedding Confluence-specific policy in the client.

In practice, v1 should treat traversal as operating on two inputs:

- page fetch for one canonical page ID
- child-ID discovery for one canonical page ID

This keeps behavior outside the client where possible and fits the existing pipeline cleanly.

For the existing stub path, traversal can continue to derive child IDs from the stub payload's `children` field.

For `--client-mode real`, traversal should use the new real child-ID listing function instead of expecting `fetch_real_page` to populate `children`.

## Traversal Semantics

### Depth definitions

v1 uses the existing depth semantics:

- the root page is depth `0`
- direct children are depth `1`
- grandchildren are depth `2`
- each additional parent-to-child edge adds `1` depth

Examples:

- `--tree --max-depth 0`: include only the root page
- `--tree --max-depth 1`: include the root page and its direct children
- `--tree --max-depth 2`: include the root page, children, and grandchildren

### Traversal strategy

v1 traversal should be breadth-first and deterministic.

Required behavior:

1. Resolve `--target` to the canonical root page ID.
2. Fetch the root page through the existing real page-fetch path.
3. If `max_depth` is `0`, stop after the root page.
4. For each depth level from `0` up to `max_depth - 1`, list child page IDs for the pages in the current frontier.
5. Deduplicate discovered child page IDs before fetching the next frontier.
6. Sort the next frontier by canonical page ID in ascending lexical order.
7. Fetch each next-frontier page through the existing real page-fetch path, in that sorted order.
8. Repeat until `max_depth` is reached.

This produces a stable external order:

- root page first
- all depth `1` pages before any depth `2` page
- all depth `2` pages before any depth `3` page
- lexical canonical-ID ordering within the same depth

v1 does not preserve parent adjacency in output order. Determinism is more important than mirroring source response order.

## Deduplication Rules

Deduplication remains based only on canonical page ID.

Rules:

- each canonical page ID is fetched at most once per run
- each canonical page ID is written at most once per run
- each canonical page ID appears at most once in the manifest

When the same child page ID appears more than once:

- repeated IDs within one parent's child list are ignored after the first occurrence
- repeated IDs across different parents at the same depth are included only once in the next frontier
- rediscovery at a deeper depth does not trigger another fetch or another output entry

Because traversal is breadth-first, the shallowest discovered depth wins automatically.

If the same canonical page ID is discovered at multiple depths:

- the first shallowest depth determines inclusion
- later rediscovery does not change ordering or reporting

## Ordering Expectations

Ordering should be deterministic even if Confluence returns child pages in an unstable order.

v1 ordering contract:

- traversal is breadth-first
- root depth `0` always appears first
- ordering within a depth level is canonical page ID ascending lexical order
- deduplication happens before finalizing each depth level

This keeps output, dry-run reporting, and manifest ordering stable and easy to test with mocks.

## Error Behavior

v1 error handling is intentionally simple and fail-fast.

Traversal should stop on the first unrecoverable error. It should not attempt retries, partial continuation, or best-effort skipping.

### Child-list fetch failure

If the real client cannot fetch the child list for a page because the request fails or returns a source error:

- stop traversal immediately
- surface the first error
- do not continue to siblings or descendants
- do not write page markdown files
- do not write or replace `manifest.json`

### Malformed child-list response

If the child-list response cannot be validated into the required `list[str]` child-ID shape, treat it as unrecoverable.

Examples:

- response body is not valid JSON
- response payload shape is not the expected collection shape
- child entries cannot be mapped to canonical page IDs
- a child ID is empty after mapping

Behavior:

- stop traversal immediately
- surface a response-validation error
- do not continue processing additional pages
- do not write page markdown files
- do not write or replace `manifest.json`

### Missing child IDs

Missing child IDs are treated as a malformed child-list response, not as silently skippable entries.

Examples:

- a child item is present but has no usable page ID
- a child item maps to `null`, `""`, or a non-string value

Behavior:

- fail the run
- stop on the first such error

### Page fetch failure for a discovered page

If traversal discovers a descendant page ID but fetching that page fails:

- stop traversal immediately
- surface the first page-fetch error
- do not fetch remaining queued pages
- do not write page markdown files
- do not write or replace `manifest.json`

This uses the same fail-fast model as the existing recursive contract and fits the current pipeline cleanly because traversal completes before writing begins.

## Auth and Integration Boundaries

This design preserves the current real-client auth boundary.

v1 rules:

- keep `--client-mode real` opt-in
- keep the existing supported real auth mode unchanged
- reuse the existing auth helper for both page fetches and child-list fetches
- do not add certificate-based auth, mTLS, or other new auth modes in this phase

Integration rules:

- no manifest contract changes are required for v1 real traversal
- no writer contract changes are required for v1 real traversal
- no incremental-sync contract changes are required for v1 real traversal

The only new integration point is the traversal layer calling the real child-ID listing function when `--client-mode real` and `--tree` are both enabled.

## Testing Strategy

`make check` must not require live Confluence access.

v1 traversal should be covered with mocked or monkeypatched responses:

- traversal tests that inject page-fetch and child-list callables
- real-client mapping tests with canned child-list JSON payloads
- CLI contract tests that run `--client-mode real --tree --max-depth N` with mocked child-list and page-fetch responses

Recommended assertions:

- root-only behavior at `--max-depth 0`
- child inclusion at `--max-depth 1`
- grandchild inclusion at `--max-depth 2`
- breadth-first lexical ordering
- canonical-ID deduplication across repeated child listings
- fail-fast stopping on child-list failures
- fail-fast stopping on malformed child-list responses
- fail-fast stopping on descendant page-fetch failures
- absence of markdown and manifest writes on failure

Live validation against a real Confluence instance may be useful for developer confidence, but it should remain optional and outside normal `make check` validation.

## Out of Scope

The following are explicitly out of scope for this phase:

- pagination or rate-limit sophistication
- retries, backoff, or resume behavior
- attachments
- comments
- richer child metadata beyond canonical child page IDs
- auth expansion, including certificate-based auth and mTLS
- making the real client the default
- broad refactors unrelated to enabling real tree traversal

## Future Enhancements

The following may be considered later, but are not part of v1:

- pagination support for large child lists
- retry/backoff policy for transient errors
- richer child metadata for reporting or manifest use
- partial-success or resumable traversal
- live incremental-sync optimizations based on child discovery data

v1 should stay intentionally smaller than those future directions.
