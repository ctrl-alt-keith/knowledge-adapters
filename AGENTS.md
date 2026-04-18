# AGENTS.md

## Repository purpose
This repository contains generic adapters for acquiring and normalizing external knowledge sources into local, LLM-ready artifacts.

The current implementation focus is the Confluence adapter.

## Safety and scope rules
- Keep the repository public-safe.
- Never hardcode secrets, tokens, cookies, internal URLs, or environment-specific values.
- Do not add live integration logic that requires private systems for tests.
- Prefer sanitized fixtures and stubs over real remote access.

## Engineering rules
- Prefer minimal, reversible changes.
- Do not perform broad rewrites unless explicitly requested.
- Preserve the current adapter contract and repository shape unless the task requires a focused improvement.
- Keep source-specific details runtime-injected.

## Validation
Before considering a task complete, run:

```bash
ruff check . --fix
mypy src
pytest
```