# Confluence Adapter

## Purpose

The Confluence adapter is the repository's first adapter scaffold. This document is
the authoritative status page for what the default Confluence CLI currently does.

This adapter is the first implementation of the generic adapter contract for `knowledge-adapters`.

## Current Behavior

Out of the box, the default Confluence CLI:

- accepts a page ID or full page URL as input
- validates full page URLs against `--base-url` and requires the URL to include
  the page ID
- accepts `--base-url`, `--client-mode`, `--auth-method`, `--output-dir`,
  `--dry-run`, `--tree`, and `--max-depth`
- resolves the target into a canonical page ID
- normalizes page ID and full page URL targets into the same resolved source URL
  for stub-mode metadata and dry-run reporting
- keeps dry-run and write output aligned around the same resolved page ID,
  canonical source URL, page artifact path, and manifest path
- fetches stub page data for that resolved page
- supports an opt-in real client path with `--client-mode real` for live page
  fetches and breadth-first tree traversal using `bearer-env` or
  `client-cert-env` auth
- keeps `stub` and `real` modes on the same CLI flow and artifact layout, with
  only the content source changing between modes
- keeps dry-run and write messaging aligned across `stub` and `real`, including
  the same plan header, artifact-path reporting, and write/skip summary shape
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

## Design and Contract Docs

The following docs define intended behavior beyond the current default client:

- [`docs/adapter-spec.md`](../../docs/adapter-spec.md): generic adapter contract
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
