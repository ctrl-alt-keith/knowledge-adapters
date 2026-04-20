# Feature Delivery Workflow

## Purpose

This document explains what "feature delivery" should look like in
`knowledge-adapters`.

Reusable lifecycle models, review patterns, and prompt templates now belong in
`ai-workflow-playbook`. This file keeps the repo-specific guidance needed to
ship changes here without depending on that playbook.

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

## Repo-Specific Delivery Expectations

When delivering a feature in this repo:

1. work from a new branch based on `main`
2. keep the change focused on the requested adapter, CLI path, or doc surface
3. preserve public-safe defaults and avoid checking in secrets or private system
   details
4. validate through `make check`
5. commit, push, and open a PR targeting `main`

Open the PR as ready for review by default unless the task explicitly calls for
a draft.

`AGENTS.md` remains the canonical source for branch naming, validation, commit
messages, and completion requirements.

## Feature-Specific Guardrails

Keep feature work grounded in the current design of this repo:

- avoid broad shared abstractions unless multiple adapters already need them
- keep source-specific logic inside the relevant adapter package
- update tests when behavior changes, especially around contract boundaries
- avoid mixing live-integration work with unrelated cleanup
- keep docs accurate to the current CLI, CI, and branch-protection baseline

## CI And Merge Baseline

The local and CI validation path for feature work is `make check`.

The current enforced baseline on `main` is:

- pull requests are required
- admins are included in branch protection
- the required status check is `test`
- required approving review count is `0`

That baseline is intentionally minimal. Repo docs may recommend a stricter
working style, but they should not imply stronger enforced GitHub rules than
those settings.
