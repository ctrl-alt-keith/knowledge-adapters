# Knowledge Adapters Project Map

This document provides a concise, human-readable view of the current state of
the repository, active work, and upcoming arcs. It complements GitHub issues by
grouping them into meaningful lanes.

This repository currently implements the **Source Acquisition Product
Candidate**. The Product Candidate owns the bounded acquisition transaction and
Source Package semantics; this repository controls only its accepted source,
current implementation, validation, review, and merge facts.

## Current State

- Confluence adapter: mature (single-page, tree traversal, incremental sync,
  space discovery by key/URL, TLS/auth, portable CA bundle overrides,
  environment-specific config overrides, opt-in fetch and traversal caches,
  progress output)
- Git repo ingestion: complete (`git_repo` adapter, polish, and example config)
- GitHub metadata ingestion: v1 complete (`github_metadata` adapter for
  GitHub/GHE issues, pull requests, releases, optional issue comments, and
  optional pull request comments/review comments)
- Public-source acquisition: `public_webpage` and `public_pdf` adapters,
  replay-quality diagnostics, and replay-acceptance checks complete
- YouTube: `youtube` source-package adapter complete
- Source Package contract: provider-neutral producer-to-consumer interchange,
  construction and verification APIs complete (experimental contract)
- Google Docs publication: integrated into this repository as the separately
  invoked `publish` command implementing the **Publication Product Candidate**
  (#356). It is not a source adapter, and neither `run` nor `bundle` publishes.
  The former separate `ka-destinations` implementation is retired
- Bundle command:
  - v1 complete (#147)
  - ordering controls added (#153)
  - include/exclude filters added (#152)
  - header modes added (#155)
  - changed-only bundle comparison complete (#157)
  - size-aware bundle splitting complete (#154)
  - `--config` without `--bundle` renders every configured bundle (#355)
- Config-driven runs, named bundle definitions, stale-aware bundling, CLI,
  interrupt handling, and test coverage are stable

## Next Arcs

### New adapters

#### GitHub metadata ingestion

- Keep future additions usage-driven and bounded, such as release assets,
  changed paths, labels, milestones, reviews, or checks

## Principles

- Prefer small arcs that touch one surface area
- Do not mix bundle work with adapter work in the same PR
- Keep new adapters generic and bounded
- Let real usage drive design-heavy features
- Avoid turning features into frameworks prematurely
