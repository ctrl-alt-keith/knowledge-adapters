# knowledge-adapters

Generic adapters for acquiring knowledge from external sources and normalizing it into local, LLM-ready artifacts.

---

## Quickstart

```bash
git clone <repo>
cd <repo>

make check-env
make dev
make check
```

Common commands:

```bash
make check-env
make test
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
- Confluence adapter scaffold
- local files adapter scaffold
- CLI entrypoint
- basic end-to-end pipeline (resolve → fetch stub → normalize → write)
- CI (ruff, mypy, pytest)
- initial unit tests

### Planned MVP
- Confluence adapter
  - accept a page URL or page ID
  - accept runtime-provided auth
  - fetch a target page or page tree
  - normalize output to markdown plus metadata
  - write local artifacts to a specified output directory
  - track state with a manifest
  - support dry-run behavior
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

## Example

Normalize a local text file into the standard markdown artifact:

```bash
knowledge-adapters local_files \
  --file-path ./notes/today.txt \
  --output-dir ./artifacts
```
