# Codex Workflow

## Purpose

This document captures the preferred way to use Codex in this repository.

Codex is most effective here when used for small, bounded, reviewable tasks in an isolated branch or worktree. The goal is to accelerate implementation without losing control of scope, repo hygiene, or validation.

---

## Core model

Use Codex as a focused contributor for PR-sized changes.

Preferred pattern:

1. Start from a clean `main`
2. Work in an isolated branch or worktree
3. Give Codex one bounded task
4. Review the diff
5. Run validation
6. Commit, push, and open a PR
7. Merge only after review and CI pass

Do not use Codex as the source of truth for architecture. Use it to implement and refine within an already-defined repo structure.

A task is not complete until a pull request has been created.

---

## Where Codex fits

Use Codex for:
- adding or improving tests
- tightening edge-case handling
- improving CLI behavior
- refining normalization logic
- making small, focused refactors
- preparing commit and PR summaries

Do not use Codex first for:
- broad architectural redesigns
- large cross-cutting refactors
- live private-system integrations
- browser automation
- adding multiple new adapters at once

---

## Thread strategy

Use one Codex project for this repository.

Use one Codex thread per PR-sized task.

Stay in the same thread when:
- continuing the same task
- making follow-up fixes for the same PR
- addressing review comments on the same change

Start a new thread when:
- starting a new branch/worktree
- changing task scope
- moving to a different PR-sized change
- the previous thread has become confusing or overloaded

Good rule:
- one thread = one branch/worktree = one PR-sized task

---

## Branch and PR strategy

Preferred branch naming format:

<type>/<area>-<short-description>

Examples:
- test/resolve-edge-cases
- test/normalize-writer
- feat/confluence-cli-smoke-test
- fix/resolve-url-parsing

Keep branch names:
- lowercase
- hyphen-separated
- short but descriptive
- scoped to one change

PR titles should mirror branch intent, for example:
- test: expand resolve_target edge cases
- feat: add CLI dry-run smoke test

PR descriptions should follow this structure:

Summary
- high-level description of the change
- key implementation details

Testing
- how the change was validated (typically `make check`)

---

## Task prompt pattern

Use prompts that are explicit about:
- isolation from `main`
- task scope
- constraints
- validation
- delivery format

Example:

Work in an isolated branch or worktree based on main. Never work directly on main.

Task:
Add edge-case tests for resolve_target().

Focus on:
- URLs without page IDs
- malformed or unexpected inputs
- whitespace handling
- preserving current intended behavior unless a small, clearly justified fix is needed

Constraints:
- Follow AGENTS.md
- Keep changes minimal, focused, and reversible
- Do not introduce live Confluence access
- Do not add new dependencies
- Do not refactor unrelated code
- Prefer tests first; only change production code if necessary to support correct behavior

Validation:
Run the full local validation before considering the task complete:
- make check

Do not consider the task complete until:
- changes are committed
- the branch is pushed
- a pull request is created

Delivery:
When done:
1. summarize files changed
2. summarize behavior covered by the new tests
3. list any assumptions
4. commit using Conventional Commits format
5. push the branch
6. open a PR with a concise summary

If anything blocks completion, stop and explain the blocker clearly instead of broadening scope.

---

## Planning guidance

For simple tasks, ask Codex to implement directly.

For harder or less clearly scoped tasks, ask Codex to plan first before changing code.

Use planning first when:
- the task touches multiple modules
- the task is ambiguous
- the task might require production-code changes
- there are several possible implementation paths

---

## Validation

The canonical validation steps for this repo are defined in `AGENTS.md`.

A Codex task is not considered complete until validation succeeds.

At the time of writing, validation is:

```bash
make check
```