# AGENTS

Start with `ai-workflow-playbook/docs/start-here.md`.

## File Placement

- Put adapter implementation under `src/knowledge_adapters/<source>/`.
- Put tests under `tests/`.
- Put repo documentation under `docs/`.
- Keep source-specific supporting material under `adapters/<source>/` when that
  repo path already exists for the integration.

## Validation

`make check` is the canonical local blocking validation entrypoint. It runs:

- `make lint`
- `make typecheck`
- `make test`

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

`make chaos-all` and `make chaos-replay` are advisory or diagnostic targets.
They do not replace `make check` and are not hidden release gates.

`make check` must stay deterministic and must not require live provider access,
network credentials, GitHub authentication, or release permissions. Optional
live-provider validation remains outside normal repository validation and must
be reported separately when used.

Run `make check-gh-env` before pull request or release workflows that require
an authenticated `gh` session. Release-only targets such as `make release-check`
and `make release-publish` are scoped to the documented release workflow and are
not part of normal local PR validation.
