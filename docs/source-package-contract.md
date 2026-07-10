# Source Package Contract

Status: design draft for contract approval. This document defines an
interchange boundary; it does not define adapter implementation, a CLI, or a
vault ingestion pipeline.

## Purpose And Boundary

A source package is a portable custody record produced by a source adapter and
consumed by a review system such as `knowledge-vault`. It describes one bounded
acquisition run, the resources considered, candidate representations produced,
and failures or limitations encountered.

The stable boundary is:

```text
source request -> adapter acquisition -> immutable source package
                                      -> consumer validation and review
                                      -> retained editorial judgment
```

The adapter owns acquisition. The consumer owns review and retention. A valid
package is eligible to enter review; it is never approval to retain, trust, or
publish its content. This extends the boundary in
[`chain-of-custody.md`](chain-of-custody.md) without replacing it.

## Adapter Responsibilities

An adapter must:

- validate and record its effective, non-secret input;
- resolve each requested source into stable provider and resource identities;
- acquire only the bounded source scope requested by the operator;
- normalize acquired material into inspectable candidate representations;
- preserve provenance from the requested locator through any redirect,
  discovery, or child-resource relationship;
- write a self-contained package manifest, item records, candidate artifacts,
  diagnostics, and a content inventory;
- assign a terminal outcome to every discovered item, including partial
  failures and deliberate skips;
- make completed work resumable without silently changing prior results;
- distinguish deterministic transformation from live-provider observation;
- exclude credentials and minimize sensitive data;
- produce deterministic ordering, relative paths, and hashes for captured
  bytes and normalized artifacts; and
- identify the contract and adapter versions used.

## Non-Responsibilities

An adapter does not:

- decide truth, importance, relevance, licensing approval, or retention;
- mark content as reviewed, trusted, retained, or publishable;
- write into a consumer's retained-content or catalog paths;
- create summaries presented as the consumer's editorial judgment;
- infer permission to acquire adjacent resources outside the requested scope;
- hide partial failures behind an overall successful run;
- require a consumer to understand provider-specific payloads for baseline
  review; or
- retain destination state, downstream analysis, or vault review decisions.

## Input Contract

An adapter receives a logical acquisition request. The transport and user
interface are deliberately unspecified. The request contains:

| Field | Requirement | Meaning |
| --- | --- | --- |
| `request_id` | required | Caller-assigned idempotency and audit identifier. |
| `adapter_type` | required | Stable adapter family, such as `video-host`, `feed`, `document`, or a source-specific family. |
| `targets` | required | Ordered list of explicit locators or stable source identifiers. |
| `scope` | required | Bounded acquisition intent, such as one resource, a collection, or descendants with an explicit limit. |
| `output_location` | required | Local package destination; not a retained-content destination. |
| `credential_reference` | optional | Opaque runtime reference. Secret values never enter the package. |
| `selection` | optional | Time, item-count, language, media, or update filters with explicit semantics. |
| `checkpoint_reference` | optional | Compatible prior run or adapter-local checkpoint from which to resume. |
| `retry_policy` | optional | Operator limits; the effective policy is recorded in the receipt. |
| `expected_contract` | optional | Consumer-supported contract range used for fail-fast compatibility checks. |

Requests must separate source identity from credentials and execution tuning.
Provider-specific options are permitted in a namespaced extension object, but
they must not alter the meaning of common fields or become necessary to read
baseline provenance and outcomes.

## Output Contract

### Package Shape

```text
source-package/
├── package.json
├── request.json
├── items/
│   └── <item-id>.json
├── artifacts/
│   └── <item-id>/
│       └── normalized.md
├── diagnostics/
│   └── <item-id>.json
└── run-receipt.json (optional)
```

All manifest paths are package-relative, use `/` separators, and cannot escape
the package root. Files are UTF-8 JSON or UTF-8 markdown unless an artifact
entry declares another media type. Raw provider responses and large binaries
are optional, quarantined artifacts rather than required package content.

`package.json` is the authoritative inventory and contains:

- `contract_name`: `knowledge-source-package`;
- `contract_version`: semantic version of this interchange contract;
- `package_id`, `request_id`, `run_id`, and `created_at`;
- adapter name, adapter version, and build or revision identity when available;
- run status and counts by item outcome;
- effective non-secret request reference;
- ordered item-record references;
- ordered artifact inventory with byte size, media type, and SHA-256 digest;
- immutable resume or supersession lineage when applicable, including prior
  package or run identifiers, a reconciliation summary, and final attempt
  counts;
- optional sealed `run-receipt.json` reference for additional immutable run
  history;
- deterministic/live boundary statement;
- package-level diagnostics and limitations; and
- optional namespaced extensions.

Each item record contains:

- stable package item ID and provider-neutral resource kind;
- requested, resolved, and canonical source locators as applicable;
- provider and provider resource identity in namespaced provenance;
- source title, creator or publisher, publication/update time, and language
  when observed, with absence represented as absence rather than invention;
- parent or collection relationships needed to reconstruct acquisition scope;
- acquisition time and observation token when supplied by the provider;
- item outcome and structured error or skip reason;
- references to candidate artifacts and diagnostics;
- hashes for captured and normalized forms when those forms exist;
- normalization name/version and disclosed transformations; and
- terms, license, access, or sensitivity observations as evidence only, never
  as a retention decision.

Required item outcomes are `completed`, `unchanged`, `skipped`, `failed`, and
`cancelled`. A sealed package has status `completed` only when every item is
terminal and none failed or was cancelled, or `completed_with_errors` when
every item is terminal and at least one failed or was cancelled. Both statuses
are conforming sealed consumer handoffs when terminal accounting and package
integrity are complete. `in_progress` exists only in adapter-local runtime
state and is never a sealed consumer handoff. When a run cannot produce a valid
inventory, its package-level `failed` result is emitted as a run receipt or
diagnostic result rather than as a conforming source package. Item-level
failures remain valid inside a `completed_with_errors` sealed package.

### Package Integrity

A sealed package is immutable. Its inventory must cover every handoff file
except explicitly ephemeral lock files, and every inventoried file must match
its recorded digest and size. Consumers may copy or quarantine a package but
must not edit it in place. Corrections produce a new package with lineage to
the superseded package.

## Lifecycle And State Machine

```text
requested -> resolving -> acquiring -> normalizing -> sealing
    |            |            |             |            |
    +---------- checkpointable in-progress states -------+
                                                         v
                          completed | completed_with_errors
```

Item state proceeds independently:

```text
discovered -> acquiring -> acquired -> normalizing -> completed
                   |                         |
                   +-> failed                +-> failed
discovered -> skipped
any in-progress state -> cancelled
```

Transitions are adapter-local runtime observations. A run that fails before it
can seal a valid inventory ends in a separate failed run receipt or diagnostic
result. The sealed package contains terminal item state plus enough immutable
lineage to explain retries and resume; it need not expose an unbounded event
log or mutable execution state.

## Checkpoint And Resume Semantics

A checkpoint is mutable adapter-local runtime state. It is not part of a sealed
source package, is not a consumer handoff artifact, and is not durable
knowledge. It may record the request fingerprint, adapter and contract
versions, provider cursor or continuation token, completed item identities and
digests, pending work, retry counters, and last successful boundary.

Resume must:

- reject a changed request fingerprint unless an explicit new run is started;
- verify checkpoint compatibility and completed artifact integrity;
- preserve completed item outputs when their identity and observation token
  still match;
- continue from a provider cursor only when the provider documents it as safe;
- otherwise restart discovery and deterministically reconcile by canonical
  identity;
- assign a new `run_id` while retaining immutable resume lineage; and
- never convert a prior failure into success without a recorded new attempt.

The sealed handoff records resume history without depending on checkpoint
state. At minimum this includes `resumes_run_id` when applicable, prior package
or run identifiers, a reconciliation summary, and final attempt counts. An
optional sealed `run-receipt.json` may carry additional immutable history. The
package remains self-contained and verifiable after adapter-local checkpoints
and provider cursors are deleted.

Exactly-once provider acquisition is not promised. The contract promises
idempotent package assembly: duplicate observations reconcile by stable item
identity and content digest, while every attempt remains diagnosable.

## Retry Behavior

Retries are bounded, observable, and scoped to the smallest safe unit. Each
attempt records ordinal, time, failure category, and whether the adapter judged
it retryable. Delay durations need not be preserved unless operationally
useful.

Adapters may retry transient transport, throttling, and provider-availability
failures. They must not automatically retry invalid configuration,
authentication denial requiring operator action, unsupported content,
contract violations, or deterministic normalization failures. Provider hints
may inform timing but cannot override operator limits. Exhausted retries end in
an item-level `failed` outcome; independent items continue unless the request
requires atomic discovery or the operator cancels.

## Deterministic And Live-Provider Boundaries

Live acquisition is an observation, not a reproducible computation. Adapters
must record acquisition time, resolved locator, provider observation token
such as a revision or entity tag when available, and captured-byte digest.

Given identical captured bytes, normalization configuration, normalization
version, and contract version, artifact bytes and inventory ordering must be
deterministic. Timestamps, retry history, provider order, signed URLs, and
credentials cannot influence normalized content. Provider ordering must be
converted to a documented stable order or preserved as explicit source order.

Replay tests begin at the captured-byte boundary. Live-provider checks are
separate evidence and are never part of deterministic contract validation.

## Schema Versioning And Compatibility

The contract uses semantic versions:

- patch: clarification or validation tightening that does not change valid
  package meaning;
- minor: backward-compatible optional additive fields and namespaced
  extensions. A new artifact role is minor only when older consumers can safely
  ignore it;
- major: required-field changes and semantic changes to terminal accounting,
  identity, integrity, lifecycle, or review-relevant meaning. Non-ignorable
  artifact roles require a major version unless they declare a required
  capability that causes older consumers to reject the package safely.

New package or item outcomes are major-version changes by default. A new
outcome may be minor only when it is explicitly defined as a
backward-compatible subtype or alias of an existing outcome and declares a safe
legacy mapping.

Consumers declare a supported version range. Producers must not emit a version
outside an explicitly supplied range. Consumers must reject unsupported major
versions, ignore unknown optional fields, preserve unknown extension data when
copying a package record, and reject unknown required capabilities listed in
`package.json`.

Provider evolution belongs in namespaced item extensions. A provider-specific
field can enter the common contract only after multiple adapters demonstrate
the same consumer need and portable meaning.

## Testing Strategy

Contract approval should lead to tests at four boundaries:

- schema fixtures: minimal valid, complete valid, and one invalid fixture per
  invariant;
- producer conformance: deterministic output, ordering, hashing, path safety,
  terminal accounting, redaction, and partial failure;
- checkpoint/retry tests: interruption at each state, resume lineage,
  corrupted checkpoint rejection, transient recovery, and exhausted retry;
- consumer compatibility: current and previous supported minor versions,
  unknown optional fields, unknown required capabilities, digest mismatch,
  unsupported major version, and malicious paths.

Provider tests use recorded, sanitized fixtures or deterministic stubs. Small
live-provider canaries are optional, credentialed, separately reported, and do
not establish contract conformance.

## Illustrative Example Package

This illustrative package represents a two-episode podcast feed in which one
episode was captured and one failed after bounded retries. JSON files are shown
inline; the artifact content is intentionally short. Placeholder sizes and
digests are non-normative and must not be used as a conformance fixture.

```text
source-package/
├── package.json
├── request.json
├── items/episode-001.json
├── items/episode-002.json
├── artifacts/episode-001/normalized.md
├── diagnostics/episode-002.json
└── run-receipt.json
```

`request.json`:

```json
{"request_id":"podcast-sample-2026-07-10","adapter_type":"feed","targets":["https://example.org/show/feed.xml"],"scope":{"kind":"collection","max_items":2},"selection":{}}
```

`package.json`:

```json
{
  "contract_name": "knowledge-source-package",
  "contract_version": "1.0.0",
  "package_id": "pkg-podcast-sample-001",
  "request_id": "podcast-sample-2026-07-10",
  "run_id": "run-002",
  "resumes_run_id": "run-001",
  "prior_run_ids": ["run-001"],
  "reconciliation_summary": {"reused":1,"retried":1},
  "final_attempt_counts": {"episode-001":1,"episode-002":3},
  "created_at": "2026-07-10T18:00:00Z",
  "adapter": {"name":"example-feed-adapter","version":"1.2.0"},
  "status": "completed_with_errors",
  "counts": {"completed":1,"unchanged":0,"skipped":0,"failed":1,"cancelled":0},
  "request_path": "request.json",
  "items": ["items/episode-001.json","items/episode-002.json"],
  "artifacts": [
    {"path":"artifacts/episode-001/normalized.md","role":"normalized-content","media_type":"text/markdown","bytes":"<non-normative-size>","sha256":"<non-normative-sha256>"},
    {"path":"diagnostics/episode-002.json","role":"diagnostic","media_type":"application/json","bytes":"<non-normative-size>","sha256":"<non-normative-sha256>"},
    {"path":"run-receipt.json","role":"run-receipt","media_type":"application/json","bytes":"<non-normative-size>","sha256":"<non-normative-sha256>"}
  ],
  "run_receipt": "run-receipt.json",
  "boundary": {"live":"feed discovery and media retrieval","deterministic":"transcript normalization and package assembly"},
  "required_capabilities": []
}
```

`items/episode-001.json`:

```json
{
  "item_id":"episode-001",
  "resource_kind":"audio-episode",
  "requested_locator":"https://example.org/show/feed.xml",
  "canonical_locator":"https://example.org/show/episodes/1",
  "provenance":{"provider":"example-feed","provider_resource_id":"ep-1","parent_item_id":"feed-example-show"},
  "title":"Designing Stable Boundaries",
  "publisher":"Example Show",
  "published_at":"2026-07-01T09:00:00Z",
  "acquired_at":"2026-07-10T17:55:00Z",
  "observation_token":"feed-guid-ep-1",
  "outcome":"completed",
  "artifacts":[{"path":"artifacts/episode-001/normalized.md","role":"normalized-content"}],
  "normalization":{"name":"transcript-to-markdown","version":"1.0.0","transformations":["speaker labels preserved","timestamps omitted"]},
  "rights_observations":{"license":null,"terms_url":"https://example.org/terms"}
}
```

`items/episode-002.json`:

```json
{
  "item_id":"episode-002",
  "resource_kind":"audio-episode",
  "canonical_locator":"https://example.org/show/episodes/2",
  "provenance":{"provider":"example-feed","provider_resource_id":"ep-2","parent_item_id":"feed-example-show"},
  "title":"Review Is A Product Decision",
  "acquired_at":"2026-07-10T17:58:00Z",
  "outcome":"failed",
  "error":{"category":"provider-unavailable","retryable":true,"attempts":3,"diagnostic_path":"diagnostics/episode-002.json"},
  "artifacts":[]
}
```

`artifacts/episode-001/normalized.md`:

```markdown
# Designing Stable Boundaries

Candidate transcript for review.
```

`diagnostics/episode-002.json`:

```json
{"item_id":"episode-002","attempts":[{"ordinal":1,"category":"provider-unavailable"},{"ordinal":2,"category":"provider-unavailable"},{"ordinal":3,"category":"provider-unavailable"}]}
```

`run-receipt.json`:

```json
{"receipt_version":"1.0.0","run_id":"run-002","resumes_run_id":"run-001","prior_run_ids":["run-001"],"reconciliation_summary":{"reused":1,"retried":1},"final_attempt_counts":{"episode-001":1,"episode-002":3}}
```

The placeholder sizes and digests are illustrative only. A conforming producer
must calculate exact values over exact serialized bytes.

## Future Extensibility

The common model supports collections and individual items, alternate
representations, captions, transcripts, pages, attachments, and structured
metadata without naming a provider. Extensions may add provider cursors,
chapter data, feed metadata, document page maps, or site crawl evidence under a
reverse-domain namespace. Multiple artifacts can describe one item, but every
artifact needs a declared role and content type.

The vault should not change when a new provider appears. It changes only when a
new common semantic capability is deliberately adopted or a new major contract
is approved.

## Unresolved Design Questions

1. Should v1 require a formal JSON Schema file at approval, or begin with prose
   plus conformance fixtures?
2. Are raw captured bytes permitted inside a handoff package by default, or
   only by explicit request and sensitivity policy?
3. Should timestamps require whole-second UTC normalization, or preserve
   provider precision?
4. Is SHA-256 sufficient as the only required digest, or should the inventory
   allow a required algorithm profile?
5. Which resume details belong directly in `package.json` versus an optional
   sealed `run-receipt.json`?

## Recommended Defaults

- Start at contract `1.0.0` with JSON Schema plus normative valid and invalid
  fixtures.
- Require normalized markdown only when meaningful; otherwise allow a typed
  metadata-only item.
- Exclude raw bytes by default and include them only under an explicit,
  policy-aware artifact role.
- Require SHA-256, UTC RFC 3339 timestamps, stable item ordering, and immutable
  sealed packages.
- Continue independent items after failure and report
  `completed_with_errors`.
- Support the current major and previous minor package versions during an
  announced migration window.

## Risks

- A contract that mirrors one provider will force vault changes for every new
  source.
- A contract that is too abstract will omit evidence reviewers actually need.
- Optional-field growth can become an undocumented second schema.
- Resuming from unstable provider cursors can miss or duplicate resources.
- Candidate artifacts may contain secrets, personal data, or copyrighted
  material even when structurally valid.
- Consumers may mistake `completed` or high extraction quality for retention
  approval unless the custody boundary stays explicit.

## Proposed Implementation Phases After Contract Approval

1. Ratify vocabulary, JSON Schemas, fixtures, and compatibility policy in both
   repositories.
2. Add producer conformance validation and package sealing in
   `knowledge-adapters`, without a provider migration.
3. Add vault-side quarantine validation and review-record linkage against
   fixtures.
4. Migrate one bounded adapter and one vault review example end to end.
5. Add checkpoint/resume and partial-failure conformance tests.
6. Migrate additional adapters incrementally; promote common fields only from
   demonstrated cross-provider needs.
