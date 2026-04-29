.PHONY: dev test smoke lint fix format typecheck check check-env check-gh-env chaos-random chaos-all release-notes release-check release-publish clean

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
RUFF = $(VENV)/bin/ruff
MYPY = $(VENV)/bin/mypy
PYTEST = $(VENV)/bin/pytest
CLI = $(VENV)/bin/knowledge-adapters
RELEASE_VERSION = $(patsubst v%,%,$(VERSION))
RELEASE_TAG = v$(RELEASE_VERSION)
CHAOS_SEED ?= $(shell date +%s)
CHAOS_SCENARIO ?=

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

chaos-random: $(VENV)/bin/activate
	@set -e; \
	seed="$(CHAOS_SEED)"; \
	scenario="$(CHAOS_SCENARIO)"; \
	if [ -z "$$scenario" ]; then \
		scenario="$$(CHAOS_SEED="$$seed" $(PYTHON) -c 'import os; from tests.chaos import select_chaos_scenario; print(select_chaos_scenario(os.environ["CHAOS_SEED"]).value)')"; \
	else \
		CHAOS_SCENARIO="$$scenario" $(PYTHON) -c 'import os; from tests.chaos import AdapterChaosScenario; AdapterChaosScenario(os.environ["CHAOS_SCENARIO"])'; \
	fi; \
	echo "Chaos seed: $$seed"; \
	echo "Chaos scenario: $$scenario"; \
	echo "Rerun: make chaos-random CHAOS_SEED=$$seed CHAOS_SCENARIO=$$scenario"; \
	$(PYTEST) -m chaos -k "$$scenario"

chaos-all: $(VENV)/bin/activate
	$(PYTEST) -m chaos

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

release-notes:
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required. Usage: make release-publish VERSION=0.8.1" >&2; \
		exit 1; \
	fi
	@if ! printf '%s\n' '$(RELEASE_VERSION)' | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$$'; then \
		echo "Error: VERSION must be X.Y.Z or vX.Y.Z." >&2; \
		exit 1; \
	fi
	@awk -v version='$(RELEASE_VERSION)' '\
		BEGIN { found = 0; printed = 0 } \
		$$0 == "## " version { found = 1; next } \
		found && /^## / { exit } \
		found { print; if ($$0 !~ /^[[:space:]]*$$/) printed = 1 } \
		END { \
			if (!found) { \
				printf "Error: CHANGELOG.md missing section ## %s.\n", version > "/dev/stderr"; \
				exit 1; \
			} \
			if (!printed) { \
				printf "Error: CHANGELOG.md section ## %s has no release notes.\n", version > "/dev/stderr"; \
				exit 1; \
			} \
		}' CHANGELOG.md

release-check: check-gh-env
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required. Usage: make release-publish VERSION=0.8.1" >&2; \
		exit 1; \
	fi
	@if ! printf '%s\n' '$(RELEASE_VERSION)' | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$$'; then \
		echo "Error: VERSION must be X.Y.Z or vX.Y.Z." >&2; \
		exit 1; \
	fi
	@awk -v version='$(RELEASE_VERSION)' '\
		BEGIN { found = 0; printed = 0 } \
		$$0 == "## " version { found = 1; next } \
		found && /^## / { exit } \
		found { print; if ($$0 !~ /^[[:space:]]*$$/) printed = 1 } \
		END { \
			if (!found) { \
				printf "Error: CHANGELOG.md missing section ## %s.\n", version > "/dev/stderr"; \
				exit 1; \
			} \
			if (!printed) { \
				printf "Error: CHANGELOG.md section ## %s has no release notes.\n", version > "/dev/stderr"; \
				exit 1; \
			} \
		}' CHANGELOG.md >/dev/null
	@if [ "$$(git branch --show-current)" != "main" ]; then \
		echo "Error: release must run from main after the release PR is merged." >&2; \
		exit 1; \
	fi
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: working tree must be clean before release." >&2; \
		git status --short; \
		exit 1; \
	fi
	@git fetch origin main >/dev/null
	@if [ "$$(git rev-parse HEAD)" != "$$(git rev-parse origin/main)" ]; then \
		echo "Error: local main must match origin/main. Run 'git pull --ff-only origin main' and retry." >&2; \
		exit 1; \
	fi
	@if git rev-parse --verify --quiet "refs/tags/$(RELEASE_TAG)" >/dev/null; then \
		echo "Error: local tag $(RELEASE_TAG) already exists." >&2; \
		exit 1; \
	fi
	@remote_tag_status=0; \
	git ls-remote --exit-code --tags origin "refs/tags/$(RELEASE_TAG)" >/dev/null 2>&1 || remote_tag_status=$$?; \
	if [ "$$remote_tag_status" -eq 0 ]; then \
		echo "Error: remote tag $(RELEASE_TAG) already exists." >&2; \
		exit 1; \
	elif [ "$$remote_tag_status" -ne 2 ]; then \
		echo "Error: unable to check remote tag $(RELEASE_TAG)." >&2; \
		exit 1; \
	fi
	@release_view=$$(gh release view "$(RELEASE_TAG)" 2>&1 >/dev/null); \
	release_status=$$?; \
	if [ "$$release_status" -eq 0 ]; then \
		echo "Error: GitHub release $(RELEASE_TAG) already exists." >&2; \
		exit 1; \
	elif ! printf '%s\n' "$$release_view" | grep -Eiq 'not found|could not find'; then \
		echo "Error: unable to check GitHub release $(RELEASE_TAG): $$release_view" >&2; \
		exit 1; \
	fi
	@echo "Release checks passed for $(RELEASE_TAG)."

release-publish: release-check
	@set -e; \
	notes_file=$$(mktemp); \
	trap 'rm -f "$$notes_file"' EXIT; \
	awk -v version='$(RELEASE_VERSION)' '\
		BEGIN { found = 0; printed = 0 } \
		$$0 == "## " version { found = 1; next } \
		found && /^## / { exit } \
		found { print; if ($$0 !~ /^[[:space:]]*$$/) printed = 1 } \
		END { \
			if (!found) { \
				printf "Error: CHANGELOG.md missing section ## %s.\n", version > "/dev/stderr"; \
				exit 1; \
			} \
			if (!printed) { \
				printf "Error: CHANGELOG.md section ## %s has no release notes.\n", version > "/dev/stderr"; \
				exit 1; \
			} \
		}' CHANGELOG.md > "$$notes_file"; \
	git tag -a "$(RELEASE_TAG)" -m "Release $(RELEASE_TAG)"; \
	git push origin "$(RELEASE_TAG)"; \
	gh release create "$(RELEASE_TAG)" --title "$(RELEASE_TAG)" --notes-file "$$notes_file"; \
	echo "Published GitHub release $(RELEASE_TAG)."

clean:
	rm -rf $(VENV)
