# AGENTS

This file defines repository-specific expectations for Codex agents working in
`knowledge-adapters`.

Reusable AI workflow patterns now belong in `ai-workflow-playbook`. Keep this
file focused on how this repository operates.

---

## Completion Requirements

For implementation tasks, the task is not complete until all of the following are done:

- changes are made on a new branch (not `main`)
- `make check` passes
- changes are committed
- the branch is pushed
- a pull request targeting `main` is created

Do not stop after making local file changes.
The task is only complete once the pull request exists.

---

## Git Conventions

### Start State

For same-repo arcs:

- start from fresh `origin/main`
- do not reuse an old feature branch unless intentionally continuing that PR
- use isolated worktrees or directories for same-repo parallel arcs
- treat repository identity and execution-container identity as separate checks

### Branch Naming

Use the following patterns:

- feat/<short-name>
- fix/<short-name>
- chore/<short-name>
- docs/<short-name>
- refactor/<short-name>
- test/<short-name>

---

### Commit Messages

Use Conventional Commits:

- feat: ...
- fix: ...
- chore: ...
- docs: ...
- refactor: ...
- test: ...

Avoid generic messages like:
- "Add X"
- "Update Y"

Preferred format:

<type>: <short summary>

Optional body:
- bullet points describing key changes

The commit message should reflect the PR summary and include key changes when non-trivial.

---

## Validation

Before committing or opening a PR:

```bash
make check
```

Run validation through the Makefile targets for this repository.
Do not invoke `pytest`, `mypy`, or `ruff` directly; use `make check` and other documented `make` targets instead.

If lint issues are auto-fixable:

```bash
make fix
make format
make check
```

Do not open a PR if `make check` fails.

---

## Tooling Assumptions

- Git is configured and push access is available
- GitHub CLI (`gh`) is installed and authenticated

Use `gh` to create pull requests when needed.

If `gh` is required but unavailable, explicitly report it instead of stopping early.

---

## Pull Requests

Pull requests must:

- target `main`
- include a clear summary of changes
- include a testing/verification section

PR scope integrity:
- a PR is not complete unless its diff contains only the intended arc

Issue auto-close:
- issue-driven PRs must include `Closes #<issue number>` before merge

GitHub enforcement on `main` is intentionally minimal:

- pull requests are required
- admins are subject to the same branch protection
- the required status check is `test`
- required approving review count is `0`

This file documents the repo-local working agreement on top of that enforced
baseline.

Preferred PR structure:

Summary
- high-level description of the change
- key implementation details

Testing
- how the change was validated (typically `make check`)
