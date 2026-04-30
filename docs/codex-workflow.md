# Codex Workflow

## Purpose

This document captures how to use Codex effectively in `knowledge-adapters`.

For shared workflow rules, use:

- `AGENTS.md` for repo-local execution requirements
- `ai-workflow-playbook/docs/start-here.md` for the canonical workflow entry
  point
- `ai-workflow-playbook/docs/tool-adapters/codex.md` for Codex-specific
  workflow behavior
- `ai-workflow-playbook/docs/repo-readiness.md` and
  `ai-workflow-playbook/docs/review-packet.md` for PR readiness and review
  expectations

This file keeps only the `knowledge-adapters` details that are worth knowing
while using Codex in this repository.

## What Codex Is Best Used For Here

Codex is most useful in this repo for small, reviewable changes such as:

- adapter contract and edge-case tests
- CLI behavior and smoke-test updates
- normalization, traversal, resolve, and manifest logic changes
- focused documentation updates tied to current repo behavior
- small refactors inside an existing adapter or shared CLI path

Use extra care before asking Codex to drive:

- broad architecture changes across multiple adapters
- new abstractions before a shared pattern is proven
- live private-system integration work without explicit task constraints
- unrelated cleanup mixed into the same branch

For branch, PR, and validation workflow, follow `AGENTS.md` plus the playbook
references above instead of treating this document as a second source of truth.

## Repository Guardrails

Keep changes aligned with the shape of this repository:

- preserve the separation between adapter-specific code and shared CLI behavior
- keep Confluence-specific behavior isolated to the Confluence adapter paths
- avoid committing secrets, private URLs, tokens, or internal content
- prefer contract and smoke coverage when changing adapter behavior
- keep changes minimal and reversible when working on traversal, normalization,
  or incremental-sync behavior
- when working on CLI or adapter behavior, check nearby docs and examples so
  command semantics, dry-run behavior, and artifact expectations stay accurate
