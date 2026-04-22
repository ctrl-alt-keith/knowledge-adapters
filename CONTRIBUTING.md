# Contributing

Thanks for your interest in contributing to this repository.

This project is designed to be **public-safe, reproducible, and adapter-focused**. The goal is to make it easy to add new knowledge adapters while keeping source-specific logic isolated and configuration external.

---

## Development Setup

This document is for **repo-local development**. If you only want to install
and run the CLI as an end user, use the installed-user workflow in
`README.md` instead of the `make` commands below.

Bootstrap your local development environment:

```bash
make check-env
make dev
```

These commands will:
- verify local development prerequisites
- create a local `.venv`
- install all development dependencies (`pytest`, `ruff`, `mypy`, etc.)

> Note: You do not need to manually activate the virtual environment when using `make` targets.

GitHub authentication is not required for local setup or `make check`.
GitHub-specific workflows stay explicit through:

```bash
make check-gh-env
```

Use `make check-gh-env` before opening pull requests, cutting releases, or
running any other workflow that depends on an authenticated GitHub CLI session.

---

## Common Commands

These commands are for contributors working from a clone of this repository.
Installed CLI users should not need them.

```bash
make check-env      # verify local development prerequisites
make check-gh-env   # verify GitHub CLI install + auth for PR/release workflows
make test        # run tests
make lint        # check linting (ruff)
make fix         # auto-fix lint issues where possible
make format      # format code (ruff)
make typecheck   # run mypy
make check       # lint + typecheck + test
```

If something fails, a common workflow is:

```bash
make fix
make format
make check
```

---

## Project Structure

- `src/knowledge_adapters/`
  - Source-specific adapters (e.g., Confluence)
- `tests/`
  - Unit tests for adapter logic
- `pyproject.toml`
  - Dependency and tool configuration

Each adapter should:
- fetch data from a source
- normalize it into a consistent local format (e.g., Markdown)
- avoid embedding environment-specific configuration

---

## Design Principles

### 1. Public-Safe by Default
- Do not commit secrets, tokens, or credentials
- Do not include internal URLs or identifiers
- Do not commit real source data unless sanitized

### 2. Adapter-Oriented
- Keep source-specific logic isolated
- Avoid cross-adapter coupling
- Prefer small, composable modules

### 3. Runtime Configuration
- Inject configuration at runtime (env vars, config files, etc.)
- Do not hardcode environment-specific values

### 4. Normalize Early
- Convert external data into a predictable internal format as early as possible
- Downstream logic should not depend on source-specific structure

---

## Typing Guidelines

- Use `Mapping[...]` for read-only inputs instead of `dict[...]`
- Prefer explicit types for function boundaries
- Keep normalization layers flexible (`object` is acceptable for external input)

Example:

```python
from collections.abc import Mapping

def normalize_to_markdown(data: Mapping[str, object]) -> str:
    ...
```

---

## Testing

- Add tests for all normalization logic
- Keep tests deterministic and independent of external systems
- Use fixtures or mock data instead of real API calls

Run tests with:

```bash
make test
```

---

## Linting and Formatting

This project uses Ruff for linting and formatting.

Check issues:

```bash
make lint
```

Auto-fix issues:

```bash
make fix
```

Format code:

```bash
make format
```

---

## Type Checking

This project uses Mypy for static type checking.

```bash
make typecheck
```

---

## Pull Requests

Before submitting a PR:

```bash
make check
```

Ensure:
- tests pass
- linting passes
- type checking passes

---

## Adding a New Adapter

When adding a new adapter:

1. Create a new module under `src/knowledge_adapters/<source>/`
2. Implement:
   - data fetch logic
   - normalization logic
3. Add tests under `tests/`
4. Ensure output is consistent with existing adapters

---

## Questions / Ideas

If you’re unsure about structure or design, open an issue or start a discussion.

The project is intentionally evolving—clarity and consistency matter more than strict rules.
