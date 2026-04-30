# AGENTS

This file defines repository-specific expectations for Codex agents working in
`knowledge-adapters`.

This repository follows the shared workflow defined in the
`ai-workflow-playbook` repository.

- Engineering baseline: `ai-workflow-playbook/docs/engineering-baseline.md`
- Workflow rules: `ai-workflow-playbook/docs/`
- Start here: `ai-workflow-playbook/docs/start-here.md`

Use the playbook for general workflow rules. Follow this AGENTS.md for
repo-specific execution details where they are more specific. Repo-local rules
take precedence only for repo-specific behavior.
Do not restate shared workflow rules in repo docs; link to ai-workflow-playbook
and keep only repo-specific guidance.

## File Placement

- Put adapter implementation under `src/knowledge_adapters/<source>/`.
- Put tests under `tests/`.
- Put repo documentation under `docs/`.
- Keep source-specific supporting material under `adapters/<source>/` when that
  repo path already exists for the integration.

---

## Branches

- Use repo-appropriate branch prefixes such as `feat/`, `fix/`, `docs/`,
  `chore/`, `refactor/`, and `test/`.
- Keep branch names short and descriptive, for example
  `feat/<short-name>` or `docs/<short-name>`.

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

Run `make check-gh-env` before pull request or release workflows that require
an authenticated `gh` session.

---

## Pull Requests

- Target `main`.
- Include a clear summary of changes.
- Include a testing or verification section.
