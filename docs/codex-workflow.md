# Codex Workflow

## Purpose

This document captures how to use Codex effectively in `knowledge-adapters`.

For reusable prompt structures, thread habits, and broader AI workflow patterns,
see `ai-workflow-playbook`. This file keeps only the local operating details
that matter in this repository.

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

## Repo-Specific Working Agreement

`AGENTS.md` is the canonical source for task completion requirements in this
repo. In practice, that means:

1. start from `main` and work on a new branch
2. keep the branch scoped to one PR-sized change
3. run validation through the Makefile, not direct tool invocations
4. do not consider the task complete until the change is committed, pushed, and
   opened as a PR targeting `main`

Branch names should follow the patterns in `AGENTS.md`, such as
`feat/<short-name>` or `docs/<short-name>`.

PRs should be ready for review by default and should include:

- a short `Summary` section
- a short `Testing` section

## Repository Guardrails

Keep changes aligned with the shape of this repository:

- preserve the separation between adapter-specific code and shared CLI behavior
- keep Confluence-specific behavior isolated to the Confluence adapter paths
- avoid committing secrets, private URLs, tokens, or internal content
- prefer contract and smoke coverage when changing adapter behavior
- keep changes minimal and reversible when working on traversal, normalization,
  or incremental-sync behavior

## Validation And CI

The canonical local validation command is:

```bash
make check
```

Use the Makefile targets documented in this repo. Do not invoke `pytest`,
`mypy`, or `ruff` directly when validating a task for completion.

GitHub Actions mirrors that local path in `.github/workflows/ci.yml` through the
`test` job, which runs `make check`.

The enforced baseline on `main` is currently:

- pull requests are required
- admin enforcement is enabled
- the required GitHub status check is `test`
- required approving review count is `0`

Do not rely on stronger GitHub enforcement than that baseline when writing or
updating repo docs.
