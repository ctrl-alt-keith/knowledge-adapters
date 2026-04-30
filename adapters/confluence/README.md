# Confluence Adapter

## Purpose

The Confluence adapter is the repository's first adapter scaffold. This document is
the authoritative status page for what the default Confluence CLI currently does.

This adapter is the first implementation of the generic adapter contract for `knowledge-adapters`.

## Shared CLI Flow

Confluence follows the same product-level CLI flow as `local_files`:

- inspect one source input
- plan a markdown artifact under `pages/`
- plan `manifest.json` in the output directory
- write only when `--dry-run` is not set

The Confluence-specific difference is that dry runs and write runs may report
`write` or `skip` for a page when an existing manifest entry and on-disk
artifact already match the planned output.

## Recommended First Run

Start with a single-page dry run in the default `stub` mode before trying tree
mode or live Confluence fetches:

```bash
knowledge-adapters confluence \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts \
  --dry-run
```

That first run resolves the target into a canonical page ID, previews
`pages/12345.md`, previews `manifest.json`, and prints normalized markdown
without contacting a live Confluence instance or requiring credentials.

`--target` accepts either a numeric page ID or a full page URL under
`--base-url`. Full page URLs are validated and normalized to canonical
`pageId` form for dry-run and write reporting.

If that dry run looks right, rerun the same command without `--dry-run` to
write the stub artifact and `manifest.json`.

For live Confluence content, keep the same CLI flow and add `--client-mode
real` plus an auth method:

- `bearer-env` via `CONFLUENCE_BEARER_TOKEN`
- `client-cert-env` via `CONFLUENCE_CLIENT_CERT_FILE` plus optional
  `CONFLUENCE_CLIENT_KEY_FILE`

Real-mode request pacing is optional. Add `--request-delay-ms` or
`--max-requests-per-second` to slow live Confluence API calls during page
fetches and listing/discovery. If both are provided, the slower interval between
request starts is used.

Treat tree mode as a follow-on step. With the default `stub` client, `--tree`
still plans only the resolved root page because no child pages are discovered.

## Tree Mode After First Run

- `--tree` switches the run from one resolved page to the resolved root page
  plus any discovered descendants.
- `--max-depth` counts descendant depth from that root page: `0` includes only
  the root page, `1` adds direct children, and `2` adds grandchildren.
- In `--dry-run`, tree mode previews the resolved root page ID, planned
  `manifest.json` path, unique page count, and one `would write` or `would skip`
  line per planned page. It does not write files.
- In write mode, tree mode performs the same planned writes and skips, then
  writes `manifest.json`.
- With the default `stub` client, tree mode still plans only the root page
  because no child pages are discovered. Multi-page tree runs require
  `--client-mode real` or a monkeypatched client that returns child page IDs.

## Current Behavior

Out of the box, the default Confluence CLI:

- accepts a page ID or full page URL as input
- validates full page URLs against `--base-url` and requires the URL to include
  the page ID
- accepts `--base-url`, `--client-mode`, `--auth-method`, `--output-dir`,
  `--dry-run`, `--tree`, and `--max-depth`
- resolves the target into a canonical page ID
- normalizes page ID and full page URL targets into the same resolved source URL
  for metadata, dry-run reporting, and write reporting
- keeps dry-run and write output aligned around the same resolved page ID,
  canonical source URL, page artifact path, and manifest path
- fetches stub page data for that resolved page
- supports an opt-in real client path with `--client-mode real` for
  contract-tested live page fetches and breadth-first tree traversal using
  `bearer-env` or `client-cert-env` auth
- supports opt-in fetch and traversal caches with explicit cache controls:
  `--force-refresh` bypasses configured cache reads while still writing fresh
  entries, and `--clear-cache` clears only configured Confluence cache subtrees
  before the run starts
- supports opt-in real-client request pacing with `--request-delay-ms` and
  `--max-requests-per-second`
- keeps `stub` and `real` modes on the same CLI flow and artifact layout, with
  only the content source changing between modes
- keeps dry-run and write messaging aligned across `stub` and `real`, including
  the same invocation, plan, action, and summary shape for single-page runs
- normalizes the stub page into markdown plus metadata
- writes a deterministic page artifact and `manifest.json` on normal runs
- supports dry-run output and manifest-based skip logic for the resolved page
- includes tree-mode plumbing, but the default client returns no children, so
  out-of-the-box tree runs still produce only the root page

## Known Limitations

- the default client does not make live Confluence network requests
- `--client-mode real` supports `bearer-env` via `CONFLUENCE_BEARER_TOKEN`
  and `client-cert-env` via `CONFLUENCE_CLIENT_CERT_FILE` plus optional
  `CONFLUENCE_CLIENT_KEY_FILE`
- real mode is contract-tested, but not fully live-validated across Confluence
  environments
- recursive traversal semantics are defined and tested, but multi-page tree runs
  still require `--client-mode real` or a monkeypatched client that returns child
  pages
- incremental sync semantics are defined and tested, but with the default client
  they only affect the resolved root-page artifact

## Runtime Inputs

These values are still part of the intended adapter surface and must be provided at
runtime rather than committed:

- Confluence base URL
- auth method and credential reference
- target page URL or page ID
- output directory
- optional fetch mode and limits
- optional real-client request pacing

## Design and Contract Docs

The following docs define intended behavior beyond the current default client:

- [`docs/adapter-spec.md`](../../docs/adapter-spec.md): generic adapter contract
- [`docs/adapter-contract-tests.md`](../../docs/adapter-contract-tests.md):
  minimal test-only success invariants and failure-safety expectations
- [`docs/confluence-recursive-fetch.md`](../../docs/confluence-recursive-fetch.md):
  recursive traversal semantics for `--tree` and `--max-depth`
- [`docs/confluence-incremental-sync.md`](../../docs/confluence-incremental-sync.md):
  incremental sync rules and manifest-based skip semantics

Those docs describe the intended contract for a real or monkeypatched Confluence
client. They should not be read as evidence that the default client already
performs live recursive fetches.

## Non-Goals for the Current Default Client

- browser automation
- attachments
- comments
- complete macro fidelity
- every auth flow
- publishing to external systems
