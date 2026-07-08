# Chain Of Custody Boundary

This document names the product boundary for `knowledge-adapters`.

`knowledge-adapters` owns the acquisition transaction. It turns configured
source inputs into deterministic, inspectable, replayable local artifacts and
metadata that downstream systems or reviewers can evaluate.

It does not decide whether acquired content is true, worth keeping, safe to
publish, or ready for long-term retention.

## Product Role

`knowledge-adapters` is responsible for acquisition work:

- source resolution;
- fetch or acquisition from configured sources;
- normalization into stable local artifacts;
- manifests, receipts, and changed/unchanged metadata;
- diagnostics about extraction, source shape, limits, and replay quality;
- replay evidence that lets a later run be compared with an earlier run;
- review handoff packaging, including bundles.

The repository should make the acquisition event clear enough that another
system or human can review it. It should avoid becoming the place that judges
the acquired material.

## Core Invariant

Capture the transaction, not judge the cargo.

This means `knowledge-adapters` should record what was requested, what source
was reached, what was fetched or skipped, what was normalized, what artifacts
were produced, what limits or diagnostics affected the run, and what evidence
is available for replay.

It should not decide whether the content is correct, important, approved,
retained, publishable, or part of trusted long-term knowledge.

## Artifact Meaning

Artifacts produced by `knowledge-adapters` describe an acquisition event. They
are not:

- retention approvals;
- content truth claims;
- publication state;
- downstream analysis;
- human review decisions.

Manifests are custody receipts, not retention approvals.

The same principle applies to bundles, replay reports, diagnostics, acceptance
reports, and future outputs. They can describe source identity, extraction
quality, deterministic replay behavior, normalized content, known limitations,
changed resources, skipped resources, and handoff readiness. They must not be
treated as approval that the content should be kept, trusted, published, or
promoted.

## Repository Boundaries

Adjacent repositories own later lifecycle steps:

- `knowledge-vault` owns retention, review status, cataloging,
  no-promotion decisions, and committed reviewed knowledge.
- `trusted-ai-environment` owns evidence bundle contracts, chunking,
  relations, findings, synthesis, and analysis over trusted evidence.
- `ka-destinations` owns publication, destination credentials, destination
  IDs, sharing, sync, and publish state.

`knowledge-adapters` may prepare handoff material for those systems, but it
should not store their lifecycle state or make their decisions.

## Diagnostic Vocabulary

Existing and future diagnostic terms must remain acquisition diagnostics.
Examples include:

- `review-ready`;
- `diagnostic-only`;
- `unsafe-to-promote`;
- `promotion-capable`;
- `review_worth_doing`;
- `confidence`.

These terms may describe source shape, extraction quality, replayability,
determinism, normalization limits, or the expected effort for a reviewer to
inspect the acquisition result.

They must not imply approval, content value, truth, retention, or publication
readiness. For example, `review-ready` means the acquisition result appears
inspectable enough for review; it does not mean the content has passed review.
`unsafe-to-promote` is an acquisition-side diagnostic that may indicate
additional review outside `knowledge-adapters` is required. It does not mean
this repository tracks, owns, or waits for downstream decisions, and it does
not decide retention or promotion policy.

## Product Decision Filter

Use these questions when deciding whether a proposed capability belongs in this
repository:

- Does this strengthen the integrity of the acquisition transaction?
- Does this make acquisition more deterministic, reproducible, inspectable, or
  handoff-ready?
- Does this start deciding whether the content is true, valuable, retained, or
  published?
- Does this store destination or retention state that belongs elsewhere?

Capabilities that improve acquisition integrity usually fit. Capabilities that
make content judgments, retention decisions, publication decisions, or
downstream analysis usually belong in another repository.

## Non-Goals

`knowledge-adapters` does not own:

- content truth judgment;
- retention approval;
- source licensing approval;
- downstream synthesis;
- publishing or sync state;
- long-term knowledge memory;
- automatic promotion.
