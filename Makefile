.PHONY: dev test lint fix format typecheck check check-env clean

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
RUFF = $(VENV)/bin/ruff
MYPY = $(VENV)/bin/mypy
PYTEST = $(VENV)/bin/pytest

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'

dev: $(VENV)/bin/activate

check-env:
	@command -v gh >/dev/null 2>&1 || { echo "Error: GitHub CLI (gh) is required but is not installed." >&2; exit 1; }
	@gh auth status >/dev/null 2>&1 || { echo "Error: GitHub CLI authentication is required. Run 'gh auth login' and try again." >&2; exit 1; }

test: $(VENV)/bin/activate
	$(PYTEST)

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
