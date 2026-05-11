.PHONY: help dev test smoke lint fix format typecheck check fix-all check-env check-gh-env adapter-readiness chaos-random chaos-replay chaos-all release-notes release-check release-recover release-create-from-tag release-publish clean

.DEFAULT_GOAL := dev

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
RUFF = $(VENV)/bin/ruff
MYPY = $(VENV)/bin/mypy
PYTEST = $(VENV)/bin/pytest
CLI = $(VENV)/bin/knowledge-adapters
RELEASE_VERSION = $(patsubst v%,%,$(VERSION))
RELEASE_TAG = v$(RELEASE_VERSION)
CHAOS_SEED ?=
CHAOS_SCENARIO ?=
CHAOS_NODEID ?=

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'

help: ## List available repo-local Makefile targets with short descriptions.
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: $(VENV)/bin/activate ## Create or refresh the local development environment.

check-env: ## Verify local development prerequisites.
	@command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required for local development." >&2; exit 1; }

check-gh-env: ## Verify GitHub CLI availability and authentication.
	@command -v gh >/dev/null 2>&1 || { echo "Error: GitHub CLI (gh) is required but is not installed." >&2; exit 1; }
	@gh auth status >/dev/null 2>&1 || { echo "Error: GitHub CLI authentication is required. Run 'gh auth login' and try again." >&2; exit 1; }

adapter-readiness: $(VENV)/bin/activate ## Run adapter readiness diagnostics.
	@$(PYTHON) -m knowledge_adapters.adapter_readiness

test: $(VENV)/bin/activate ## Run the test suite.
	$(PYTEST)

smoke: $(VENV)/bin/activate ## Run CLI smoke tests.
	$(PYTEST) tests/test_cli_smoke.py

chaos-random: $(VENV)/bin/activate ## Run one randomly selected chaos scenario.
	@set -e; \
	seed="$(CHAOS_SEED)"; \
	if [ -z "$$seed" ]; then \
		if [ -n "$$GITHUB_SHA" ]; then \
			seed="ci-$$GITHUB_SHA"; \
		else \
			seed="$$(date +%s)"; \
		fi; \
	fi; \
	scenario="$(CHAOS_SCENARIO)"; \
	if [ -z "$$scenario" ]; then \
		scenario="$$(CHAOS_SEED="$$seed" $(PYTHON) -c 'import os; from tests.chaos import select_chaos_scenario; print(select_chaos_scenario(os.environ["CHAOS_SEED"]).value)')"; \
	else \
		CHAOS_SCENARIO="$$scenario" $(PYTHON) -c 'import os; from tests.chaos import AdapterChaosScenario; AdapterChaosScenario(os.environ["CHAOS_SCENARIO"])'; \
	fi; \
	replay_command="$$(CHAOS_SEED="$$seed" CHAOS_SCENARIO="$$scenario" $(PYTHON) -c 'import os; from tests.chaos import build_chaos_replay_command; print(build_chaos_replay_command(seed=os.environ["CHAOS_SEED"], scenario=os.environ["CHAOS_SCENARIO"]))')"; \
	echo "Chaos seed: $$seed"; \
	echo "Chaos scenario: $$scenario"; \
	echo "CHAOS_REPLAY_COMMAND: $$replay_command"; \
	CHAOS_TARGET=chaos-random CHAOS_SEED="$$seed" CHAOS_SCENARIO="$$scenario" $(PYTEST) -m chaos -k "$$scenario"

chaos-replay: $(VENV)/bin/activate ## Replay a selected chaos scenario.
	@set -e; \
	seed="$(CHAOS_SEED)"; \
	scenario="$(CHAOS_SCENARIO)"; \
	nodeid="$(CHAOS_NODEID)"; \
	if [ -z "$$scenario" ]; then \
		echo "Error: CHAOS_SCENARIO is required. Usage: make chaos-replay CHAOS_SCENARIO=<scenario> [CHAOS_SEED=<seed>] [CHAOS_NODEID=<pytest-node-id>]" >&2; \
		exit 1; \
	fi; \
	CHAOS_SCENARIO="$$scenario" $(PYTHON) -c 'import os; from tests.chaos import AdapterChaosScenario; AdapterChaosScenario(os.environ["CHAOS_SCENARIO"])'; \
	replay_command="$$(CHAOS_SEED="$$seed" CHAOS_SCENARIO="$$scenario" CHAOS_NODEID="$$nodeid" $(PYTHON) -c 'import os; from tests.chaos import build_chaos_replay_command; print(build_chaos_replay_command(seed=os.environ.get("CHAOS_SEED") or None, scenario=os.environ["CHAOS_SCENARIO"], nodeid=os.environ.get("CHAOS_NODEID") or None))')"; \
	if [ -n "$$seed" ]; then \
		echo "Chaos seed: $$seed"; \
	fi; \
	echo "Chaos scenario: $$scenario"; \
	if [ -n "$$nodeid" ]; then \
		echo "Chaos node id: $$nodeid"; \
		echo "CHAOS_REPLAY_COMMAND: $$replay_command"; \
		CHAOS_TARGET=chaos-replay CHAOS_SEED="$$seed" CHAOS_SCENARIO="$$scenario" $(PYTEST) -m chaos "$$nodeid"; \
	else \
		echo "Chaos node id: <all matching scenario tests>"; \
		echo "CHAOS_REPLAY_COMMAND: $$replay_command"; \
		CHAOS_TARGET=chaos-replay CHAOS_SEED="$$seed" CHAOS_SCENARIO="$$scenario" $(PYTEST) -m chaos -k "$$scenario"; \
	fi

chaos-all: $(VENV)/bin/activate ## Run all chaos scenarios.
	CHAOS_TARGET=chaos-all $(PYTEST) -m chaos

lint: $(VENV)/bin/activate ## Run Ruff lint checks.
	$(RUFF) check .

fix: $(VENV)/bin/activate ## Apply Ruff lint fixes.
	$(RUFF) check . --fix

format: $(VENV)/bin/activate ## Format code with Ruff.
	$(RUFF) format .

typecheck: $(VENV)/bin/activate ## Run MyPy type checks.
	$(MYPY) .

check: lint typecheck test ## Run canonical local validation.

fix-all: fix format ## Apply lint fixes and formatting.

release-notes: ## Print release notes for VERSION.
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

release-check: check-gh-env ## Run local release readiness checks for VERSION.
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
	@echo "Running canonical validation: make check"
	@$(MAKE) check || { \
		echo "Error: canonical validation failed; release-check requires 'make check' to pass." >&2; \
		exit 1; \
	}
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

release-recover: check-gh-env ## Inspect partial release state for VERSION.
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required. Usage: make release-recover VERSION=0.8.1" >&2; \
		exit 1; \
	fi
	@if ! printf '%s\n' '$(RELEASE_VERSION)' | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$$'; then \
		echo "Error: VERSION must be X.Y.Z or vX.Y.Z." >&2; \
		exit 1; \
	fi
	@local_tag_state=missing; \
	if git rev-parse --verify --quiet "refs/tags/$(RELEASE_TAG)" >/dev/null; then \
		local_tag_state=exists; \
	fi; \
	remote_tag_state=missing; \
	remote_tag_status=0; \
	git ls-remote --exit-code --tags origin "refs/tags/$(RELEASE_TAG)" >/dev/null 2>&1 || remote_tag_status=$$?; \
	if [ "$$remote_tag_status" -eq 0 ]; then \
		remote_tag_state=exists; \
	elif [ "$$remote_tag_status" -eq 2 ]; then \
		remote_tag_state=missing; \
	else \
		echo "Error: unable to inspect remote tag $(RELEASE_TAG)." >&2; \
		echo "No automatic recovery action was taken." >&2; \
		exit 1; \
	fi; \
	release_state=missing; \
	release_view=$$(gh release view "$(RELEASE_TAG)" 2>&1 >/dev/null); \
	release_status=$$?; \
	if [ "$$release_status" -eq 0 ]; then \
		release_state=exists; \
	elif printf '%s\n' "$$release_view" | grep -Eiq 'not found|could not find'; then \
		release_state=missing; \
	else \
		echo "Error: unable to inspect GitHub release $(RELEASE_TAG): $$release_view" >&2; \
		echo "No automatic recovery action was taken." >&2; \
		exit 1; \
	fi; \
	echo "Release recovery state for $(RELEASE_TAG):"; \
	echo "  local tag: $$local_tag_state"; \
	echo "  remote tag: $$remote_tag_state"; \
	echo "  GitHub release: $$release_state"; \
	if [ "$$release_state" = "exists" ]; then \
		echo "GitHub release $(RELEASE_TAG) already exists; normal recovery may be complete."; \
	elif [ "$$remote_tag_state" = "exists" ]; then \
		echo "Remote tag $(RELEASE_TAG) has already been published, but the GitHub release is missing."; \
		echo "To create the missing release from the existing remote tag, run:"; \
		echo "  make release-create-from-tag VERSION=$(RELEASE_VERSION)"; \
	elif [ "$$local_tag_state" = "exists" ]; then \
		echo "Local tag $(RELEASE_TAG) exists, but the remote tag and GitHub release are missing."; \
		echo "If the publish should be retried from scratch, delete only the local tag manually:"; \
		echo "  git tag -d $(RELEASE_TAG)"; \
	else \
		echo "No partial release publish state was found for $(RELEASE_TAG)."; \
	fi

release-create-from-tag: check-gh-env ## Create a missing GitHub release from an existing tag.
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required. Usage: make release-create-from-tag VERSION=0.8.1" >&2; \
		exit 1; \
	fi
	@if ! printf '%s\n' '$(RELEASE_VERSION)' | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$$'; then \
		echo "Error: VERSION must be X.Y.Z or vX.Y.Z." >&2; \
		exit 1; \
	fi
	@remote_tag_status=0; \
	git ls-remote --exit-code --tags origin "refs/tags/$(RELEASE_TAG)" >/dev/null 2>&1 || remote_tag_status=$$?; \
	if [ "$$remote_tag_status" -eq 2 ]; then \
		echo "Error: remote tag $(RELEASE_TAG) does not exist. No release was created." >&2; \
		exit 1; \
	elif [ "$$remote_tag_status" -ne 0 ]; then \
		echo "Error: unable to inspect remote tag $(RELEASE_TAG). No release was created." >&2; \
		exit 1; \
	fi
	@release_view=$$(gh release view "$(RELEASE_TAG)" 2>&1 >/dev/null); \
	release_status=$$?; \
	if [ "$$release_status" -eq 0 ]; then \
		echo "Error: GitHub release $(RELEASE_TAG) already exists. No release was created." >&2; \
		exit 1; \
	elif ! printf '%s\n' "$$release_view" | grep -Eiq 'not found|could not find'; then \
		echo "Error: unable to inspect GitHub release $(RELEASE_TAG): $$release_view" >&2; \
		echo "No release was created." >&2; \
		exit 1; \
	fi
	@set -e; \
	notes_file=$$(mktemp); \
	trap 'rm -f "$$notes_file"' EXIT; \
	$(MAKE) --no-print-directory release-notes VERSION='$(RELEASE_VERSION)' > "$$notes_file"; \
	gh release create "$(RELEASE_TAG)" --title "$(RELEASE_TAG)" --notes-file "$$notes_file" --verify-tag; \
	echo "Created GitHub release $(RELEASE_TAG) from existing remote tag."

release-publish: release-check ## Publish VERSION as a tag and GitHub release.
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

clean: ## Remove local development artifacts.
	rm -rf $(VENV)
