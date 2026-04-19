# Feature Delivery Workflow

## Purpose

This document defines a repeatable workflow for AI-assisted feature delivery.

It exists to keep feature work bounded, reviewable, and learnable across the full
lifecycle from idea to release. The goal is not just faster execution, but more
predictable outcomes and a workflow that improves over time.

## Core Model

Use this lifecycle as the default model for delivering a feature:

1. idea
2. design doc
3. contract tests
4. implementation
5. hardening
6. docs
7. release

Each phase should produce a clear artifact or decision before moving forward.

## Roles

### Human

The human is responsible for:

- defining the problem and intended outcome
- setting constraints, scope, and tradeoffs
- reviewing designs, diffs, and release readiness
- deciding whether to tighten, defer, or broaden work

### Codex

Codex is responsible for:

- executing bounded tasks within the stated constraints
- drafting or refining design docs and tests when asked
- implementing the requested change without expanding scope
- running validation, preparing commits, pushing branches, and opening PRs

## Feature Lifecycle

### Design

Define the feature in a short design doc before implementation when behavior is
non-trivial. The design should clarify semantics, success criteria, expected
outputs, and out-of-scope items.

### Contract Tests

Write tests that express the intended behavior before or alongside implementation.
These tests should be stable, readable, and close to user-facing expectations.

### Implementation

Implement only what is required to satisfy the design and contract tests. Avoid
adding adjacent features while code is in flight.

### Hardening

Add a small follow-up pass for edge cases, stress cases, and user-facing polish.
This phase should strengthen confidence without turning into a redesign.

### Docs & UX

Document how to use the feature and make small output improvements that help
people understand what happened. Keep output human-readable and concise.

### Release

Prepare the feature for release with versioning, changelog updates, and a release
PR. Once the release changes land on the mainline branch, create and push the
matching version tag.

## Key Principles

- Contract-first development: define expected behavior before or alongside code.
- Minimal scope per PR: one branch and one pull request should represent one
  bounded step.
- Deterministic behavior: ordering, output, and failure modes should be stable
  enough to test.
- Fail-fast over partial state: stop on unrecoverable errors instead of producing
  ambiguous partial results.
- Human-readable output: prefer concise output people can understand without extra
  tooling.
- No scope expansion during implementation: new ideas should be captured for later,
  not folded into the current task.

## Task Sizing Guidance

Good Codex tasks are:

- narrow enough to fit in one PR
- specific about behavior, constraints, and validation
- backed by a clear design or obvious acceptance criteria
- small enough to review comfortably

Avoid tasks that are:

- open-ended or architecture-first
- spread across many unrelated concerns
- dependent on unclear product decisions
- likely to trigger broad refactors just to get started

If a task feels too large, split it by lifecycle phase rather than asking for the
entire feature at once.

## Prompt Pattern

Use a consistent structure for Codex prompts:

1. isolation
2. task definition
3. constraints
4. validation
5. delivery expectations

In practice, that means prompts should explicitly state:

- work in an isolated branch or worktree based on main
- the exact task to perform
- what must not change
- how success will be validated
- what completion requires, including commit, push, and PR creation
- whether the PR should be ready for review or draft when the task is complete

Open PRs as ready for review by default.

Use a draft PR only when:

- the task explicitly asks for a draft PR
- the work is intentionally incomplete
- feedback is needed before the task is considered complete

For PR-based tasks, local validation passing is necessary but not sufficient.
After opening the PR, check the initial CI result for that branch or PR.

If that initial CI signal fails because of task-related changes, the task is not
complete yet. Continue until the failure is fixed or clearly reported as the
remaining blocker.

## Release Process

For release preparation:

1. create or update the changelog entry
2. bump the version in all relevant places so the version number, changelog
   entry, and release tag all match
3. run validation
4. commit and open a release PR with Summary and Testing sections
5. merge the release PR to the mainline branch through an allowed repository
   merge policy path
6. create a version tag that matches the released version from the merged `main`
   commit, not the branch tip
7. push the tag to origin

Keep release changes focused on release metadata and documentation. Do not mix new
feature implementation into the release PR.

The release is not complete until the release PR is actually merged into `main`.
Auto-merge may not be available in every repository, and an admin merge may be
required when allowed by repository policy.

Tag format must follow the repository's established convention going forward. In
this repository, new release tags use plain version numbers such as `0.3.0`, not
prefixed forms such as `v0.3.0`. Older tags before that convention changed may
still use the `v` prefix.

Release completion requires all of the following:

- the release PR is merged to `main` through an allowed policy path
- the correct version tag is created from the merged commit
- the tag is pushed to `origin`

## Post-Release Capture

This step is required after the release PR is merged and the version tag has been
created and pushed. It must happen before starting the next feature.

### Trigger

- after merge
- after tag push

### Goals

- capture what worked well in the feature lifecycle
- identify friction in prompts, handoffs, review, validation, or release
- refine the workflow so the next feature is easier to deliver

### Actions

- summarize the lifecycle from design through release
- note where scope drift, ambiguity, or unnecessary rework appeared
- capture workflow friction such as merge policy handling, permissions, or tagging
  issues and feed it back into workflow docs when a clear improvement is available
- update workflow docs, prompt patterns, or task templates if a clear improvement
  is available

### Principles

- lightweight
- immediate
- actionable

### Outcome

The workflow improves after each feature instead of staying static. Post-release
capture turns delivery experience into a reusable operating model for the next
feature.
