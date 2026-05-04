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

`make check` is the canonical local blocking validation entrypoint. It runs:

- `make lint`
- `make typecheck`
- `make test`

Run validation through the Makefile targets for this repository. Do not invoke
`pytest`, `mypy`, or `ruff` directly; use `make check` and other documented
`make` targets instead.

If lint issues are auto-fixable:

```bash
make fix
make format
make check
```

The pull request CI workflow also runs `make smoke` and `make chaos-random`
before `make check`. These are CI canaries outside the required local
completion path; run them locally when the task touches CLI smoke coverage,
chaos behavior, or when investigating a related failure.

`make chaos-all`, `make chaos-replay`, and `make adapter-readiness` are
advisory or diagnostic targets. They do not replace `make check` and are not
hidden release gates.

`make check` must stay deterministic and must not require live provider access,
network credentials, GitHub authentication, or release permissions. Optional
live-provider validation remains outside normal repository validation and must
be reported separately when used.

Run `make check-gh-env` before pull request or release workflows that require
an authenticated `gh` session. Release-only targets such as `make release-check`
and `make release-publish` are scoped to the documented release workflow and are
not part of normal local PR validation.

---

## Pull Requests

- Target `main`.
- Include a clear summary of changes.
- Include a testing or verification section.
