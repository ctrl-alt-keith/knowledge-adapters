# AGENTS

This file defines repository-specific expectations for Codex agents.

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

Preferred PR structure:

Summary
- high-level description of the change
- key implementation details

Testing
- how the change was validated (typically `make check`)