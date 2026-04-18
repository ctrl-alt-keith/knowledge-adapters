# AGENTS.md

## Purpose
Build and maintain adapters that acquire and normalize external knowledge sources into local, LLM-ready artifacts.

Current focus: Confluence adapter.

---

## Core principles
- Keep the repository public-safe.
- Prefer minimal, reversible changes.
- Preserve the adapter contract unless a task explicitly requires change.
- Keep all environment-specific details runtime-injected.

---

## Safety rules
- Never hardcode secrets, tokens, cookies, or internal URLs.
- Do not introduce live integration logic in tests.
- Prefer sanitized fixtures or stubs over real external systems.

---

## Engineering rules
- Avoid broad refactors unless explicitly requested.
- Change only what is required for the task.
- Keep modules focused and testable.
- Do not introduce new dependencies without justification.

---

## Validation
Before a task is considered complete, run:

```bash
ruff check . --fix
mypy src
pytest
```
