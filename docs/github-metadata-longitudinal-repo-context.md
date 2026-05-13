# GitHub Metadata Longitudinal Repo Context

## Purpose

Frame future `github_metadata` expansion as support for longitudinal
repo-context acquisition while preserving the `knowledge-adapters` boundary.

`knowledge-adapters` should acquire and normalize evidence into deterministic
local artifacts. It should not become the interpretation, stewardship,
reporting, or continuity-analysis agent.

## Boundary

The adapter boundary remains:

- read configured source material;
- normalize it into stable local artifacts;
- write deterministic manifest entries;
- expose enough metadata for downstream review and audits;
- avoid deciding what the repository means or what action should be taken.

Downstream tools, notes, review packets, or human-authored reports can interpret
the acquired evidence. The adapter should make that interpretation reproducible
by providing receipts, not conclusions.

## Why Longitudinal Context

The existing issues-only `github_metadata` contract is a useful first slice, but
repo trajectory analysis needs evidence across time rather than a single
snapshot.

Future acquisition can support questions such as:

- What has this repository repeatedly claimed it is doing?
- Which work themes recur across issues, PRs, releases, and docs?
- Which labels, milestones, changed paths, and comments show direction changes?
- Where does declared repo purpose diverge from observed behavior?
- Which evidence changed since a prior manifest-backed run?

These are acquisition questions for `knowledge-adapters` only up to the point of
capturing the evidence. Interpretation belongs elsewhere.

## Candidate Future Inputs

Candidate future `github_metadata` inputs include:

- issues;
- pull requests;
- issue and PR comments;
- releases;
- repository docs and selected metadata;
- project maps or planning surfaces when exposed through a bounded API;
- changed paths from pull requests;
- labels;
- milestones.

Each resource should be added only as a bounded adapter slice with clear
pagination, ordering, artifact, auth, and manifest behavior. The adapter should
avoid becoming a GitHub mirror.

## Deterministic Receipts

Longitudinal acquisition depends on deterministic receipts:

- stable canonical IDs per resource;
- stable artifact paths;
- deterministic ordering;
- content hashes for normalized artifacts;
- manifest-backed changed/unchanged comparison;
- explicit stale or removed-artifact reporting when supported;
- preserved source URLs and timestamps from the provider payload.

Bundles can then give downstream audits a repeatable evidence packet. Baseline
manifests can help downstream tools ask what changed without needing the adapter
to write an interpretation report.

## Lifecycle Tracking

Manifest-backed lifecycle tracking should answer acquisition-level questions:

- Which resources were acquired in this run?
- Which resources changed since the baseline manifest?
- Which previously acquired resources are no longer present or no longer in
  scope?
- Which artifacts were skipped because their normalized content was unchanged?
- Which provider or configuration limits shaped the evidence set?

Those answers support historical continuity and trajectory analysis while
remaining inside the adapter's role.

## Non-Goals

This design note does not propose:

- repo trajectory scoring;
- compliance checks;
- stewardship recommendations;
- automatic issue creation;
- cross-repo interpretation;
- semantic claims about organizational intent;
- runtime implementation changes in this PR.

The intended split is simple: `knowledge-adapters` produces deterministic
evidence bundles and manifest receipts; downstream review decides what the
evidence means.
