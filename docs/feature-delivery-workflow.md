# Feature Delivery Workflow

## Purpose

This document explains what "feature delivery" should look like in
`knowledge-adapters`.

For the shared delivery model, use:

- `AGENTS.md` for repo-local execution requirements
- `ai-workflow-playbook/docs/feature-lifecycle.md` for the canonical delivery
  lifecycle
- `ai-workflow-playbook/docs/repo-readiness.md` for PR readiness defaults
- `ai-workflow-playbook/docs/review-packet.md` for review packet expectations

This file keeps only the `knowledge-adapters` guidance that is specific to how
feature work should be shaped in this repository.

## What A Feature Usually Looks Like In This Repo

Most feature work in this repository should land as a small, reviewable PR that
improves one of these areas:

- an adapter contract or implementation
- CLI behavior around resolve, traversal, dry-run, or writing artifacts
- normalization and manifest generation
- repo documentation tied to current adapter behavior

Prefer one bounded change per branch and PR. If a request is too large, split it
along repository seams such as:

- contract tests first
- adapter implementation next
- CLI or documentation follow-up after behavior is stable

For branch, PR, and validation mechanics, follow `AGENTS.md` and the playbook
references above.

## Feature-Specific Guardrails

Keep feature work grounded in the current design of this repo:

- avoid broad shared abstractions unless multiple adapters already need them
- keep source-specific logic inside the relevant adapter package
- update tests when behavior changes, especially around contract boundaries
- avoid mixing live-integration work with unrelated cleanup
- keep docs accurate to the current CLI, output layout, and adapter behavior
- preserve public-safe defaults and avoid checking in private system details
