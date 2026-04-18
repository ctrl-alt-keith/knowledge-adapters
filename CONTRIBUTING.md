# Contributing

## Branch naming

Use the following format:

<type>/<area>-<short-description>

### Types

- feat – new functionality
- fix – bug fixes
- test – tests only
- chore – maintenance or non-functional changes

### Examples

feat/confluence-cli-smoke-test
test/resolve-edge-cases
test/normalize-writer
fix/resolve-url-parsing

### Guidelines

- lowercase only
- use hyphens (-), not spaces
- keep it short but descriptive
- include the affected area/module

---

## Pull requests

- Keep PRs small and focused on one change
- Ensure all validation checks pass:
  - ruff check . --fix
  - mypy src
  - pytest
- Include a concise summary of:
  - what changed
  - why it changed
  - any assumptions made