.PHONY: dev test smoke lint fix format typecheck check check-env check-gh-env clean

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
RUFF = $(VENV)/bin/ruff
MYPY = $(VENV)/bin/mypy
PYTEST = $(VENV)/bin/pytest
CLI = $(VENV)/bin/knowledge-adapters

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'

dev: $(VENV)/bin/activate

check-env:
	@command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required for local development." >&2; exit 1; }

check-gh-env:
	@command -v gh >/dev/null 2>&1 || { echo "Error: GitHub CLI (gh) is required but is not installed." >&2; exit 1; }
	@gh auth status >/dev/null 2>&1 || { echo "Error: GitHub CLI authentication is required. Run 'gh auth login' and try again." >&2; exit 1; }

test: $(VENV)/bin/activate
	$(PYTEST)

smoke: $(VENV)/bin/activate
	$(PYTEST) tests/test_cli_smoke.py

lint: $(VENV)/bin/activate
	$(RUFF) check .

fix: $(VENV)/bin/activate
	$(RUFF) check . --fix

format: $(VENV)/bin/activate
	$(RUFF) format .

typecheck: $(VENV)/bin/activate
	$(MYPY) .

check: lint typecheck test

fix-all: fix format

clean:
	rm -rf $(VENV)
