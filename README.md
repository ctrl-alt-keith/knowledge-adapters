# knowledge-adapters

Generic adapters for acquiring knowledge from external sources and normalizing
them into one predictable local artifact layout.

---

## Install (without cloning)

To install only the CLI, use `pipx` directly from GitHub:

```bash
pipx install git+https://github.com/ctrl-alt-keith/knowledge-adapters.git
knowledge-adapters --help
```

With a `pipx` install, use `knowledge-adapters` instead of `.venv/bin/knowledge-adapters` in the examples below.

---

## First Run (installed CLI)

Start with the built-in help so the shared flow is visible before you pick an
adapter:

```bash
knowledge-adapters --help
knowledge-adapters local_files --help
knowledge-adapters confluence --help
```

Every adapter follows the same high-level shape:

- inspect one source input
- plan a markdown artifact under `pages/`
- plan `manifest.json` in the selected output directory
- write only when `--dry-run` is not set

Recommended first run: use `--dry-run` to confirm the planned source,
artifact path, and manifest path, then rerun without it.

Minimal local file first run:

```bash
knowledge-adapters local_files \
  --file-path ./notes/today.txt \
  --output-dir ./artifacts \
  --dry-run
```

Use any existing UTF-8 text file for `--file-path`; relative paths resolve from
your current working directory.

This resolves the file path, previews `artifacts/pages/today.md`, previews
`artifacts/manifest.json`, and prints the normalized markdown without writing
files.

`local_files` accepts:

- one existing UTF-8 text file per run
- empty UTF-8 files, which still produce metadata plus an empty `Content`
  section
- directories are not supported

Files that are not valid UTF-8 text, including binary files or files saved with
another encoding, fail fast with guidance to re-save the input as UTF-8.

Recommended Confluence first run:

1. Start with the default `stub` client and `--dry-run` to confirm the resolve
   and write plan before adding credentials or contacting live Confluence.

```bash
knowledge-adapters confluence \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts \
  --dry-run
```

This resolves page `12345`, previews `artifacts/pages/12345.md` and
`artifacts/manifest.json`, and prints normalized markdown without contacting a
live Confluence instance.

`--target` accepts either a numeric page ID or a full page URL under
`--base-url`. URLs are validated and normalized to canonical `pageId` form for
artifact and manifest reporting.

2. If the dry run looks right, rerun the same command without `--dry-run` to
   write the stub artifact and `manifest.json`.

3. For live Confluence content, keep the same command shape, add
   `--client-mode real` plus auth, and start with another dry run:

- `bearer-env` -> `CONFLUENCE_BEARER_TOKEN`
- `client-cert-env` -> `CONFLUENCE_CLIENT_CERT_FILE` and optional `CONFLUENCE_CLIENT_KEY_FILE`

```bash
CONFLUENCE_BEARER_TOKEN=... knowledge-adapters confluence \
  --client-mode real \
  --auth-method bearer-env \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts \
  --dry-run
```

If that real-mode dry run looks right, rerun it without `--dry-run` to write
the live-fetched artifact and manifest.

Confluence is also the adapter that currently uses manifest-based skip logic, so
its dry runs and write runs may report `write` or `skip` for a page when an
existing artifact already matches the planned output. `local_files` always plans
one write.

---

## Local Development Setup

Use `uv` for the fastest local setup. A standard `pip` workflow is also supported.

### Using uv (recommended)

```bash
uv venv
source .venv/bin/activate
uv pip install -e .[dev]
```

### Using pip (fallback)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

---

## Developer Quickstart

```bash
git clone <repo>
cd <repo>

make check-env
make dev
make check
```

After `make dev`, the installed CLI entrypoint for this repo is:

```bash
.venv/bin/knowledge-adapters
```

Common commands:

```bash
make check-env
make test
make smoke
make lint
make fix
make format
make typecheck
```

---

## Purpose

This repository is a public-by-design workspace for building source adapters that:

- fetch knowledge from messy or structured systems
- normalize the result into a predictable local format
- keep source-specific logic separate from downstream processing
- avoid embedding environment-specific details in the codebase

The initial implementation focuses on **Confluence** and **local file** adapters, but the repository is intentionally scoped for additional adapters over time.

---

## Design Goals

- **Public-safe by default**
  - no committed secrets
  - no environment-specific URLs, tokens, or internal identifiers
  - no source content checked into the repo unless it is synthetic or sanitized

- **Adapter-oriented**
  - each source gets its own adapter
  - shared patterns live in common docs or utilities only when they are proven reusable

- **Runtime-injected configuration**
  - source URL, auth method, target page, and output location are supplied at runtime
  - work-specific details stay outside the repo

- **Normalized outputs**
  - adapters produce stable local artifacts in a common shape
  - downstream tooling should not need to understand source-specific APIs

- **Incremental and testable**
  - start with one adapter and one clean contract
  - prioritize small, reversible changes over broad abstractions

---

## Current Scope

### Implemented
- repository structure
- initial documentation
- Confluence adapter scaffold with a default stub client
- local files adapter scaffold
- CLI entrypoint
- basic end-to-end pipeline (resolve → fetch stub → normalize → write)
- Confluence single-page CLI flow for resolve, dry-run, write, and manifest generation
- CI (ruff, mypy, pytest)
- initial unit tests

### Planned MVP
- Confluence adapter
  - keep the default stub flow and opt-in real mode aligned around one CLI contract
  - continue hardening contract-tested real-mode fetch, traversal, and incremental sync behavior against live environments
- local files adapter
  - accept a runtime-provided file path
  - normalize file contents into markdown plus metadata
  - write local artifacts to a specified output directory

---

## Out of Scope for Initial MVP

- embeddings or vector databases
- search or retrieval UX
- notebook publishing
- cloud document publishing
- browser automation
- handling every Confluence macro or attachment type perfectly
- multiple source adapters in the first implementation

---

## Security Model

This repository contains only generic tooling, abstractions, and documentation.

**Never commit:**
- secrets
- tokens
- cookies
- internal URLs
- source content from private systems
- environment-specific config files

**Instead:**
- inject credentials via environment variables, CLI args, or local-only config
- keep local config and token storage outside the repo
- use synthetic or sanitized fixtures for tests

---

## Workflow

1. Define the adapter contract
2. Implement one adapter in a narrow, testable way
3. Normalize source content into stable local artifacts
4. Add tests and automation around the contract
5. Expand only after shared patterns become clear

---

## Repository Layout

```text
knowledge-adapters/
├── README.md
├── CONTRIBUTING.md
├── AGENTS.md
├── docs/
│   ├── vision.md
│   ├── adapter-spec.md
│   └── codex-workflow.md
├── adapters/
│   └── confluence/
│       └── README.md
├── src/
│   └── knowledge_adapters/
├── tests/
└── .gitignore
```

## Confluence Status

The Confluence adapter is currently a scaffolded CLI flow with a default stub
client.

### Implemented in the default CLI

- resolves a numeric page ID or full Confluence page URL into a canonical page ID
- accepts `--base-url`, `--client-mode`, `--auth-method`, `--output-dir`,
  `--dry-run`, `--tree`, and `--max-depth`
- generates stub page content for the resolved page without contacting a live
  Confluence instance
- supports an opt-in real client path with `--client-mode real` for
  contract-tested live page fetches and tree traversal using `bearer-env` or
  `client-cert-env` auth
- normalizes that stub content into markdown and writes `pages/<canonical_id>.md`
- writes `manifest.json` for normal runs
- supports dry-run output and manifest-based skip logic for the resolved page

### Design-level or contract-tested behavior

- child-page discovery that produces multi-page recursive tree runs
- recursive dry-run summaries over real discovered descendants
- production-oriented incremental sync against live-fetched Confluence content

The recursive traversal and incremental sync docs still matter: they define the
intended contract for a real or monkeypatched client. See
[`docs/confluence-recursive-fetch.md`](docs/confluence-recursive-fetch.md) and
[`docs/confluence-incremental-sync.md`](docs/confluence-incremental-sync.md) for
that design surface.

## Examples

Start with a dry run for the local files adapter:

```bash
knowledge-adapters local_files \
  --file-path ./notes/today.txt \
  --output-dir ./artifacts \
  --dry-run
```

`--file-path` should point to one existing UTF-8 text file. Relative paths
resolve from the current working directory, and directories are not supported.

Write the same local file artifact after reviewing the plan:

```bash
knowledge-adapters local_files \
  --file-path ./notes/today.txt \
  --output-dir ./artifacts
```

Start with a dry run for the default Confluence adapter:

```bash
.venv/bin/knowledge-adapters confluence \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts \
  --dry-run
```

Out of the box, this resolves page `12345`, generates stub content for that
page, previews `pages/12345.md`, previews `manifest.json`, and does not contact
a live Confluence instance.

Full page URL targets are also accepted under `--base-url` and are normalized to
canonical `pageId` form for artifact and manifest reporting.

Write the same Confluence artifact after reviewing the plan:

```bash
.venv/bin/knowledge-adapters confluence \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts
```

Run the opt-in real Confluence client for a single resolved page:

```bash
CONFLUENCE_BEARER_TOKEN=... .venv/bin/knowledge-adapters confluence \
  --client-mode real \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts
```

In v1, `--client-mode real` supports both single-page fetches and real breadth-first
tree traversal with `--tree` and `--max-depth`, using `bearer-env` auth and
optional client certificates or `client-cert-env` auth. This opt-in path is
contract-tested, but not fully live-validated across Confluence environments.

For certificate-based auth, set `CONFLUENCE_CLIENT_CERT_FILE` to a combined PEM
file, or set `CONFLUENCE_CLIENT_CERT_FILE` plus `CONFLUENCE_CLIENT_KEY_FILE` for
split cert/key files.
This v1 path is intentionally minimal: passphrase-protected keys, broader auth
combinations, and live certificate validation are out of scope for `make check`.

In both `stub` and `real` modes, the CLI keeps the same resolve, plan, action,
and summary shape. The dry run prints the planned artifact path and normalized
markdown. If an existing `manifest.json` entry and on-disk artifact already
match the resolved page, the Confluence CLI reports `would skip` instead of
`would write`.

The Confluence CLI also includes tree-mode and incremental-sync plumbing. The
default stub client still does not discover child pages, so out-of-the-box stub
tree runs yield only the resolved root page. In `--client-mode real`, the CLI
can traverse real child pages breadth-first up to `--max-depth`.

Confluence incremental skip eligibility uses the existing `manifest.json` plus
on-disk file existence. A page counts as already written only when:

- `canonical_id` matches a prior manifest entry
- `output_path` matches the current deterministic path such as `pages/12345.md`
- that file still exists on disk

If any of those checks fail, the page is treated as a write. Skipped pages still
appear in dry-run output. With the default client, this behavior applies to the
resolved root-page artifact only.

Incremental sync is artifact-based within the chosen output directory, not
target-based. Reusing an output directory for a different target is allowed, but
overlapping canonical page IDs may still be skipped when the manifest and on-disk
artifact match.

During a normal write run, the tool also writes exactly one `manifest.json` file in
the output directory. With the default single-page client, the manifest describes
the resolved page artifact written by that run.

Example shape from the default single-page Confluence client:

```json
{
  "generated_at": "2026-04-18T12:34:56Z",
  "files": [
    {
      "canonical_id": "12345",
      "source_url": "https://example.com/wiki/pages/viewpage.action?pageId=12345",
      "output_path": "pages/12345.md",
      "title": "stub-page-12345"
    }
  ]
}
```

For scaffolded tree-mode runs, the manifest keeps the same per-file entries and adds
only minimal root-run context:

```json
{
  "generated_at": "2026-04-18T12:34:56Z",
  "root_page_id": "12345",
  "max_depth": 2,
  "files": [
    {
      "canonical_id": "12345",
      "source_url": "https://example.com/wiki/pages/viewpage.action?pageId=12345",
      "output_path": "pages/12345.md",
      "title": "stub-page-12345"
    }
  ]
}
```

With the default stub client, tree mode still produces only the resolved root page
unless you replace or monkeypatch the client in tests or other integration code.
`title` is included only when it is already available as part of the current run. In
`--dry-run` mode, the tool does not create or update `manifest.json`, and it does
not create directories for the manifest.
