# Knowledge Adapters Project Map

This document provides a concise, human-readable view of the current state of
the repository, active work, and upcoming arcs. It complements GitHub issues by
grouping them into meaningful lanes.

## Current State

- Confluence adapter: mature (single-page, tree traversal, incremental sync,
  TLS/auth, progress output)
- Bundle command:
  - v1 complete (#147)
  - ordering controls added (#153)
  - changed-only bundle comparison in review (#157)
- CLI, config-driven runs, and test coverage are stable

## Active Arc

### Bundle advanced behavior

- #154 Add size-aware splitting to the bundle command
- #157 Add changed-only bundle mode based on a prior manifest

## Next Arcs

### Confluence expansion

- #148 Add Confluence space-wide page discovery via space URL or space key

### New adapters

#### Git source ingestion

- #159 Add `git_repo` adapter for ingesting repository contents

#### GitHub metadata ingestion

- #160 Add `github_metadata` adapter for issues, PRs, and releases

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
