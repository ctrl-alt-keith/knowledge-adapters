# Knowledge Adapters Project Map

This document provides a concise, human-readable view of the current state of
the repository, active work, and upcoming arcs. It complements GitHub issues by
grouping them into meaningful lanes.

## Current State

- Confluence adapter: mature (single-page, tree traversal, incremental sync,
  space discovery by key/URL, TLS/auth, portable CA bundle overrides,
  environment-specific config overrides, progress output)
- Git repo ingestion: complete (`git_repo` adapter, polish, and example config)
- GitHub metadata ingestion: issues-only v1 complete (`github_metadata` adapter
  for GitHub/GHE repository issues)
- Google Docs destination: design completed as a separate post-bundle
  publication layer, not a `knowledge-adapters` adapter or bundle subcommand
- Bundle command:
  - v1 complete (#147)
  - ordering controls added (#153)
  - include/exclude filters added (#152)
  - header modes added (#155)
  - changed-only bundle comparison complete (#157)
  - size-aware bundle splitting complete (#154)
- CLI, config-driven runs, interrupt handling, and test coverage are stable

## Next Arcs

### New adapters

#### GitHub metadata ingestion

- Split PRs, releases, and comments into follow-up issues after the issues-only
  v1 adapter proves out

## Deferred / Usage-driven

### Confluence resumability

- #146 Add optional resumable fetch cache for Confluence tree runs
- Note: only implement after confirming repeated large-run pain

### Bundle config integration

- #151 Add `runs.yaml`-defined bundles for named runs
- Note: defer until CLI bundle semantics stabilize

### Stale-aware bundling

- #156 Add stale-aware bundle handling for Confluence tree outputs
- Note: requires clearer stale-state persistence model

## Principles

- Prefer small arcs that touch one surface area
- Do not mix bundle work with adapter work in the same PR
- Keep new adapters generic and bounded
- Let real usage drive design-heavy features
- Avoid turning features into frameworks prematurely
