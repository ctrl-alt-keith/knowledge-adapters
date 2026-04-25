# Google Docs Destination Design

## Purpose

This document defines how Google Docs should fit into the
`knowledge-adapters` workflow without changing the existing ingestion,
artifact, manifest, and bundle architecture.

The target workflow is:

```text
knowledge-adapters -> bundle output -> Google Doc -> Gemini
```

The design goal is to make Google Docs a destination for already-packaged
knowledge, not a new responsibility inside `knowledge-adapters`.

## Recommendation

Google Docs integration should live outside `knowledge-adapters` as a separate
destination tool or thin publication layer.

`knowledge-adapters` should continue to own source ingestion, normalization into
local artifacts, manifest writing, and deterministic bundling. A Google Docs
publication layer should consume bundle output and publish that output into
Google Docs for use by Gemini or human collaborators.

This keeps the boundary clean:

- `knowledge-adapters` remains source-oriented and file-oriented.
- Google Docs publishing remains destination-oriented and workspace-oriented.
- Google API auth, document creation, update behavior, and workspace policy do
  not leak into adapter or bundle code.
- The same bundle output can support Google Docs, manual upload, or another
  destination without changing adapter contracts.

## System Placement

Google Docs belongs after bundle generation.

```text
Sources
  Confluence
  local files
  git repositories
  GitHub metadata
      |
      v
knowledge-adapters source adapters
  resolve -> fetch -> normalize -> persist
      |
      v
Artifact directories
  pages/*.md
  issues/*.md
  files/*.md
  manifest.json
      |
      v
knowledge-adapters bundle
  manifest-backed selection
  deterministic ordering
  include/exclude filtering
  changed-only selection
  optional size-aware splitting
      |
      v
Bundle file(s)
  bundle.md
  bundle-001.md
  bundle-002.md
      |
      v
Separate Google Docs destination layer
  publish bundle markdown
  create or update document(s)
  preserve useful source attribution
      |
      v
Google Docs document store
      |
      v
Gemini in Google Workspace
```

Google Docs should not be modeled as an adapter in v1 because adapters acquire
knowledge from sources and normalize it into local artifacts. The desired Google
Docs workflow is the reverse: take already-normalized, already-bundled output
and place it into a destination. Treating Google Docs as an adapter would blur
source ingestion with destination publication.

Google Docs should also not be added directly to the `bundle` command in v1.
The bundle command's job is to write deterministic local markdown from
manifest-backed artifacts. Publishing to a remote document store introduces
authentication, rate limits, remote document identity, partial failure behavior,
and update policy. Those are destination concerns, not packaging concerns.

## Interface Contract

The Google Docs destination layer should consume bundle output as its primary
input.

### Required Input

The minimal required input is one or more UTF-8 markdown files produced by:

```text
knowledge-adapters bundle --output <bundle.md> <adapter-output-or-manifest>...
```

For size-aware bundle output, the destination layer may accept the generated
split files:

```text
bundle-001.md
bundle-002.md
bundle-003.md
```

Each bundle file is a complete local publication unit. The destination layer may
map one bundle file to one Google Doc, or map a small set of bundle files to a
single Google Docs folder. That mapping belongs outside `knowledge-adapters`.

### Optional Structured Metadata Input

When structured metadata is needed, the destination layer may also consume the
same source `manifest.json` files that were passed to `knowledge-adapters
bundle`.

The destination layer should not require a new `knowledge-adapters` API for v1.
It can use:

- bundle markdown as the document body
- source manifests for structured attribution and idempotency hints
- operator-supplied destination configuration for Google-specific behavior

### Bundle Structure Expectations

The destination layer may rely on the existing bundle markdown structure:

```text
## <title or canonical_id>
source_url: <source URL>
canonical_id: <canonical ID>
fetched_at: <timestamp, when present>
path: <source path, when present>
ref: <source ref, when present>

<artifact markdown body>

---

## <next title or canonical_id>
...
```

Expected properties:

- files are UTF-8 markdown
- artifact sections are separated by stable horizontal-rule separators
- each section has a title line
- each section has a `source_url`
- full header mode includes `canonical_id`
- optional metadata may include `fetched_at`, `path`, and `ref`
- artifact body content is already normalized by source adapters

For v1, the Google Docs destination layer should prefer `--header-mode full` so
published documents retain source attribution and stable canonical identifiers.

### Manifest Metadata Expectations

When source manifests are supplied, the destination layer may expect:

```text
{
  "generated_at": "...",
  "files": [
    {
      "canonical_id": "...",
      "source_url": "...",
      "output_path": "...",
      "title": "...",
      "content_hash": "..."
    }
  ]
}
```

Required per-file fields for bundle compatibility are:

- `canonical_id`
- `source_url`
- `output_path`

Common optional fields are:

- `title`
- `fetched_at`
- `content_hash`
- `path`
- `ref`

The destination layer must treat manifests as local metadata about the bundle's
source material. It should not ask `knowledge-adapters` to store Google Doc IDs,
Google revision IDs, publish state, workspace folder IDs, or sync cursors in
adapter manifests.

## Responsibilities

### `knowledge-adapters` Should Do

`knowledge-adapters` should:

- fetch content from supported sources
- normalize source content into stable local markdown artifacts
- write adapter-owned `manifest.json` files
- include source identity and attribution metadata in manifests
- bundle selected artifacts into deterministic markdown
- support bundle filtering, ordering, changed-only selection, and size splitting
- keep outputs local, inspectable, and testable
- make no assumptions about Google Docs, Gemini, or Google Workspace

### `knowledge-adapters` Should Not Do

`knowledge-adapters` should not:

- call Google Docs APIs
- own OAuth consent, token refresh, or workspace auth policy
- create, update, delete, move, share, or permission Google Docs
- store Google document IDs or revision IDs in adapter manifests
- track publish status
- run background sync or polling loops
- reconcile remote document edits back into local artifacts
- turn the bundle command into a remote publishing command
- introduce a generic destination plugin system for this use case
- special-case Gemini prompt behavior inside source adapters

### Google Docs Destination Layer Should Do

The separate Google Docs destination layer should:

- accept bundle markdown file(s) as input
- optionally accept source manifest file(s) for structured metadata
- create a Google Doc from a bundle file
- optionally update an explicitly selected existing Google Doc
- preserve source attribution from bundle headers
- report the Google Doc URL after publication
- keep destination configuration outside this repository
- own Google-specific auth, API retries, and workspace errors
- keep any publish state in its own local or destination-specific state file

### Google Docs Destination Layer Should Not Do

The destination layer should not:

- fetch source systems directly
- normalize Confluence, git, local file, or GitHub content
- rewrite `knowledge-adapters` artifacts or manifests
- depend on adapter internals
- invent a second bundle format
- become a general sync engine in v1
- reconcile collaborative edits from Google Docs back to artifacts
- decide which source content should be ingested

## v1 Design Scope

The safest v1 is a separate, explicit publication step.

```text
knowledge-adapters <source> ... --output-dir artifacts/<source>
knowledge-adapters bundle artifacts/<source> --output out/bundle.md --header-mode full
google-docs-publish out/bundle.md --title "<doc title>"
```

The exact destination tool name is outside this repository. It could be a small
internal CLI, an automation script, or a manual upload process at first. The key
point is that it consumes bundle files and lives outside
`knowledge-adapters`.

### Included in v1

v1 should include:

- publish one bundle markdown file into one Google Doc
- publish split bundle files into separate Google Docs when provided
- accept an explicit document title from the operator
- preserve bundle section headings and source metadata as document text
- return or print the resulting Google Doc URL
- fail clearly on auth, permission, quota, or document write errors
- keep Google credentials and destination config outside this repository

Optional v1 behavior:

- dry-run publication planning
- operator-provided destination folder
- operator-provided existing document ID for full-document replacement
- local publish report written by the destination layer, not by
  `knowledge-adapters`

### Triggering

The v1 trigger should be explicit.

Recommended triggers, in order:

1. A separate CLI outside this repository.
2. A local script owned by the operator or workspace automation.
3. Manual upload or copy into Google Docs for early validation.

`knowledge-adapters` should not grow a `google_docs` subcommand for v1.

### Out of Scope for v1

v1 does not include:

- OAuth flow design in this repository
- Google Docs API client implementation in `knowledge-adapters`
- continuous sync
- background jobs
- webhooks
- bidirectional sync
- partial document patching
- preserving all Google Docs-native formatting
- importing Google Docs comments, suggestions, or edit history
- reconciling remote edits
- document sharing and permission policy design
- Gemini-specific prompt orchestration
- generic destination plugin architecture
- publishing directly from source adapter commands

## Avoiding Architectural Drift

The following anti-patterns would damage the current architecture:

- adding Google Docs API calls to source adapters
- adding Google Docs API calls to `knowledge-adapters bundle`
- treating Google Docs as an adapter when it is being used as a destination
- storing destination state in source manifests
- adding `google_doc_id`, `workspace_id`, `folder_id`, or `revision_id` fields
  to adapter manifest entries
- making adapters aware of Gemini or Google Workspace
- adding source-specific Google Docs formatting rules to artifact normalization
- adding a generic plugin system before more destination needs are proven
- making bundle output depend on live network access
- making bundle output non-deterministic because of destination state
- letting remote document edits become implicit source material
- mixing ingestion, packaging, publication, and sync in one command

Features to avoid inside `knowledge-adapters`:

- OAuth setup helpers
- token storage
- Google Drive folder selection
- Google Doc sharing controls
- remote document diffing
- remote revision tracking
- publish retry queues
- scheduled sync
- comment or suggestion import
- Gemini chat orchestration

The architecture stays healthy when `knowledge-adapters` remains a deterministic
producer of local artifacts and bundles, and the destination layer remains an
explicit consumer of those local files.

## Future Evolution

Future destination work can expand without changing the v1 boundary.

Potential later additions outside `knowledge-adapters`:

- publish bundle files to Google Docs with richer markdown-to-document
  formatting
- publish split bundles into a Google Drive folder with an index document
- maintain destination-owned publish state keyed by bundle file hash or
  manifest `canonical_id`
- support full-document replacement for known document IDs
- add destination tools for Notion, SharePoint, or other document stores
- add an operator-owned sync tool that watches bundle output directories

Potential later additions inside `knowledge-adapters`, only if real use proves
the need:

- document the bundle markdown format more formally
- emit an optional bundle report describing selected manifests and output files
- add bundle metadata that remains destination-neutral

Those additions should remain destination-neutral. A future bundle report, for
example, could describe bundle file paths, selected canonical IDs, source
manifest paths, byte counts, and content hashes. It should not include Google
Doc IDs or any destination-specific state.

Extensibility should come from stable files and clear ownership, not from a
generic plugin system. The first useful abstraction is the existing one:

```text
sources -> local artifacts -> manifests -> bundle files -> destination tools
```

Only after multiple destination tools have repeated the same local-file
consumption needs should this repository consider adding more destination-neutral
bundle metadata.

## Testing Strategy

For this repository, v1 testing should remain focused on existing local
contracts:

- adapter commands write artifacts and manifests
- bundle consumes manifests and artifacts
- bundle output remains deterministic
- split bundle output remains deterministic

Google Docs publication tests belong with the separate destination layer. Those
tests can use mocked Google API clients, fixture bundle files, and fixture
manifests without requiring changes to `knowledge-adapters`.

Any future `knowledge-adapters` changes should be testable without network
access and without Google credentials.

## Decision Summary

Google Docs integration should be a separate destination layer that consumes
`knowledge-adapters` bundle output.

`knowledge-adapters` should not directly publish to Google Docs in v1. It should
preserve its current architecture:

```text
ingestion -> artifacts + manifest -> bundle
```

The Google Docs layer should start small: publish bundle markdown into Google
Docs explicitly, report the resulting document URL, and keep all Google-specific
auth, document identity, workspace policy, and publish state outside this
repository.
