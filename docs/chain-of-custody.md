# Chain Of Custody Boundary

This document names the Source Acquisition boundary currently implemented in
`knowledge-adapters`.

The **Source Acquisition Product Candidate** is the **Semantic Contract
Producer** for the Source Package contract: it owns the bounded acquisition
transaction and shared contract semantics. `knowledge-adapters` currently hosts
the primary implementation and normative Source Package contract. Its source
adapters perform acquisition and emit deterministic, inspectable, replayable
local artifacts and metadata that downstream systems or reviewers can evaluate.

Neither Source Acquisition nor this repository decides whether acquired
content is true, worth keeping, authorized for publication, or ready for
long-term retention.

## Product Candidate Role

Source Acquisition owns the meaning and boundary of acquisition work:

- source resolution;
- fetch or acquisition from configured sources;
- normalization into stable local artifacts;
- manifests, receipts, and changed/unchanged metadata;
- diagnostics about extraction, source shape, limits, and replay quality;
- replay evidence that lets a later run be compared with an earlier run;
- review handoff packaging, including bundles.

Source adapters are the Runtime Producers for these outputs. The repository
currently implements those adapters, exposes their commands, and records their
accepted source, validation, review, and merge facts. The implementation should
make the acquisition event clear enough that another system or human can
review it without assigning content judgment to the repository or adapter.

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

## Product And Repository Boundaries

Adjacent Product identities own later bounded questions while repositories
currently host their implementations and evidence:

- The **Knowledge Record Enduring Product** owns the editorial-retention
  authority boundary. The Playbook's [Product Status](https://github.com/ctrl-alt-keith/ai-workflow-playbook/blob/main/docs/product-status.md#knowledge-record)
  records its current accepted status, and [Human Product Promotion Decision
  #1](https://github.com/ctrl-alt-keith/ai-workflow-playbook/blob/main/docs/product-promotion-decisions/human-product-promotion-decision-001.md),
  effective 2026-07-24, records the historical governance event that established
  it without changing that boundary. An authorized human reviewer decides
  retention, restriction, rejection, or deferral. `knowledge-vault` currently
  hosts the consumer implementation and records accepted editorial decisions.
- The **Evidence Synthesis Product Candidate** owns an identified analytical
  attempt over a frozen accepted-evidence set. Its runtime components perform
  chunking, relation extraction, finding production, and synthesis without
  turning execution into analytical approval.
- The **Publication Product Candidate** owns the authorized external-delivery
  transaction and publication-receipt semantics. A publication authorizer
  decides what exact artifact and destination are authorized.
  `ka-destinations` currently implements destination behavior and records
  publication receipts.

An operator or orchestrator may transport a sealed Source Package or bundle
between implementations. Transport does not own Source Acquisition semantics,
consumer-local policy, Publication semantics, or consequential human
decisions. `knowledge-adapters` may prepare handoff material, but it should not
store later lifecycle state or make later Product or human decisions.

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
this repository tracks or waits for downstream decisions, and it does not
decide retention or promotion policy.

## Product Decision Filter

Use these questions when deciding whether a proposed capability belongs in this
repository:

- Does this strengthen Source Acquisition's bounded transaction or shared
  contract meaning?
- Does this make acquisition more deterministic, reproducible, inspectable, or
  handoff-ready?
- Is the work a Runtime Producer or normative-contract-host implementation
  change that currently belongs in this repository?
- Does this start deciding whether the content is true, valuable, retained, or
  published?
- Does this store destination or retention state that belongs elsewhere?

Capabilities that improve acquisition integrity usually fit the Source
Acquisition boundary and may currently fit this repository. Capabilities that
make content judgments, retention decisions, publication decisions, or
downstream analysis belong to the applicable Product boundary and its current
implementation, regardless of repository convenience.

## Non-Goals

Source Acquisition does not own:

- content truth judgment;
- retention approval;
- source licensing approval;
- downstream synthesis;
- publishing or sync state;
- long-term knowledge memory;
- automatic promotion.
