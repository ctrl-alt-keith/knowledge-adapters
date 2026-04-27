# knowledge-adapters

Generic adapters for acquiring knowledge from external sources and normalizing
them into one predictable local artifact layout.

---

## Choose Your Command Context

This repository supports two different ways to run the CLI:

- **Installed CLI user**: install the published tool and run `knowledge-adapters`
- **Repo-local developer**: clone the repository, run `make` targets, and use `.venv/bin/knowledge-adapters`

Keep those contexts separate when copying commands. Installed-user examples
below use `knowledge-adapters`. Contributor and development examples use
`.venv/bin/knowledge-adapters` plus `make`.

---

## Installed CLI Setup (without cloning)

To install only the CLI, use `pipx` directly from GitHub:

```bash
pipx install git+https://github.com/ctrl-alt-keith/knowledge-adapters.git
knowledge-adapters --help
```

With a `pipx` install, use `knowledge-adapters` in the installed-user examples
below. The repo-local developer workflow later in this README uses
`.venv/bin/knowledge-adapters` instead.

---

## Installed CLI First Run

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

1. If the dry run looks right, rerun the same command without `--dry-run` to
   write the stub artifact and `manifest.json`.

1. For live Confluence content, keep the same command shape, add
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

## Confluence Authentication Examples

Bearer token via `CONFLUENCE_BEARER_TOKEN`:

```bash
CONFLUENCE_BEARER_TOKEN=example-bearer-token knowledge-adapters confluence \
  --client-mode real \
  --auth-method bearer-env \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts \
  --dry-run
```

Client certificate auth with a separate key:

```bash
knowledge-adapters confluence \
  --client-mode real \
  --auth-method client-cert-env \
  --client-cert-file ./certs/confluence-client.crt \
  --client-key-file ./certs/confluence-client.key \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts \
  --dry-run
```

Optional custom CA bundle:

```bash
knowledge-adapters confluence \
  --client-mode real \
  --auth-method bearer-env \
  --ca-bundle ./certs/internal-ca.pem \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts \
  --dry-run
```

The same settings work in `runs.yaml`:

```yaml
runs:
  - name: docs-home-bearer
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home-bearer
    client_mode: real
    auth_method: bearer-env
    dry_run: true

  - name: docs-home-mtls
    type: confluence
    base_url: https://example.com/wiki
    target: "12345"
    output_dir: ./artifacts/confluence/docs-home-mtls
    client_mode: real
    auth_method: client-cert-env
    client_cert_file: ./certs/confluence-client.crt
    client_key_file: ./certs/confluence-client.key
    ca_bundle: ./certs/internal-ca.pem
    dry_run: true
```

- `bearer-env` reads `CONFLUENCE_BEARER_TOKEN`.
- Omit `ca_bundle` to fall back to `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE`.
- Omit `client_cert_file` and `client_key_file` to fall back to
  `CONFLUENCE_CLIENT_CERT_FILE` and `CONFLUENCE_CLIENT_KEY_FILE`.
- Explicit CLI flags or `runs.yaml` values override those env fallbacks.

Confluence is also the adapter that currently uses manifest-based skip logic, so
its dry runs and write runs may report `write` or `skip` for a page when an
existing artifact already matches the planned output. `local_files` always plans
one write.

## Run Multiple Sources from One Config File

For sequential multi-source refreshes, copy the committed example config and
edit the local working file:

```bash
cp runs.example.yaml runs.yaml
```

Update `runs.yaml` with the sources and output directories you want, then run:

```bash
knowledge-adapters run runs.yaml
```

The config uses a top-level `runs:` list. Each run includes a `name`, a `type`,
adapter-specific inputs such as `base_url`/`target` or `file_path`, and its own
`output_dir`. `runs.example.yaml` is committed for reference, while `runs.yaml`
is gitignored for local use.

### Bundle Usage

Bundle one or more existing adapter outputs directly:

```bash
knowledge-adapters bundle ./artifacts/confluence/docs-home --output ./bundle.md
```

Render a named bundle from `runs.yaml`:

```bash
knowledge-adapters bundle --config ./runs.yaml --bundle review-pack
```

Use `runs.yaml` for repeatable workflows. `--stale-mode include|exclude|flag`
controls how bundle rendering handles explicit stale-artifact metadata. See
`runs.example.yaml` for fuller bundle and named-bundle examples.

---

## Repo-Local Development Setup

These steps are for contributors working from a local clone of this repository.
If you only want to use the CLI, stay in the installed-user sections above and
skip the developer setup below.

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

## Repo-Local Developer Quickstart

```bash
git clone <repo>
cd <repo>

make check-env
make dev
make check
```

`make check-env` verifies only the local prerequisites for development. GitHub
authentication is not required to create the virtualenv, install dependencies,
or run local validation.

After `make dev`, the repo-local CLI entrypoint for this checkout is:

```bash
.venv/bin/knowledge-adapters
```

## Integration Tests

Use the normal fast local loop when you are iterating on unit, contract, and
CLI behavior that does not need a live subprocess:

```bash
.venv/bin/pytest -m "not integration"
```

Run the integration slice explicitly when you want to exercise real adapter
wiring against the local Confluence stub:

```bash
.venv/bin/pytest -m integration
```

These integration tests start [`tools/confluence_stub/app.py`](./tools/confluence_stub/app.py)
locally with `uvicorn`, talk only to `localhost`, and use committed stub data
from [`tools/confluence_stub/data/pages.json`](./tools/confluence_stub/data/pages.json)
so the responses stay deterministic and do not require real Confluence
credentials.

Common commands:

```bash
make check-env      # verify local development prerequisites
make check-gh-env   # verify GitHub CLI install + auth for PR/release workflows
make test
make smoke
make lint
make fix
make format
make typecheck
```

Run `make check-gh-env` before GitHub-dependent workflows such as opening pull
requests or performing release steps that require an authenticated `gh`
session.

---

## Purpose

This repository is a public-by-design workspace for building source adapters that:

- fetch knowledge from messy or structured systems
- normalize the result into a predictable local format
- keep source-specific logic separate from downstream processing
- avoid embedding environment-specific details in the codebase

The initial implementation focuses on **Confluence** and **local file**
adapters, but the repository is intentionally scoped for additional adapters
over time.

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
  - continue hardening contract-tested real-mode fetch, traversal, and
    incremental sync behavior against live environments
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

### Installed CLI Examples

These examples assume you installed the tool with `pipx` and are running the
global `knowledge-adapters` command.

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
knowledge-adapters confluence \
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
knowledge-adapters confluence \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts
```

Run the opt-in real Confluence client for a single resolved page:

```bash
CONFLUENCE_BEARER_TOKEN=... knowledge-adapters confluence \
  --client-mode real \
  --base-url https://example.com/wiki \
  --target 12345 \
  --output-dir ./artifacts
```

### Repo-Local Developer Examples

These examples assume you cloned the repository, ran `make dev`, and are using
the local virtual environment entrypoint.

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

### Traversal Cache Behavior

Traversal cache is opt-in with `--tree-cache-dir` or `tree_cache_dir`.
Cached listings are reused without freshness validation.
Clear or change the cache directory when tree structure changes.

> Traversal cache entries are operator-managed. Clear or change the cache
> directory when pages are added, removed, or reorganized.

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

During a normal write run, the tool also writes exactly one
`manifest.json` file in the output directory. With the default single-page
client, the manifest describes the resolved page artifact written by that run.

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

For scaffolded tree-mode runs, the manifest keeps the same per-file entries and
adds only minimal root-run context:

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

With the default stub client, tree mode still produces only the resolved root
page unless you replace or monkeypatch the client in tests or other integration
code. `title` is included only when it is already available as part of the
current run. In `--dry-run` mode, the tool does not create or update
`manifest.json`, and it does not create directories for the manifest.
