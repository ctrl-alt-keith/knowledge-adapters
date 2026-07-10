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

## Normative Ownership

`knowledge-adapters` owns this normative Source Package Contract. This document
is the canonical source for shared interchange vocabulary, package structure,
package semantics, compatibility rules, lifecycle definitions, integrity
requirements, and producer/consumer handoff behavior.

Consumers such as `knowledge-vault` may document derived summaries and
consumer-specific review policy, but they do not independently redefine this
contract. If a consumer summary conflicts with this document, this document
governs. The companion vault expectations are documented in
[`knowledge-vault`](https://github.com/ctrl-alt-keith/knowledge-vault/blob/main/docs/source-package-consumer-contract.md).

## Participants

The interchange has three roles:

- the adapter is the producer and owns the acquisition transaction and sealed
  package;
- the vault is the consumer and owns validation for review, editorial review,
  and retention decisions; and
- the operator or orchestrator invokes adapters, supplies runtime credential
  references, selects supported compatibility ranges, transfers sealed
  packages, manages quarantine, preserves package bytes during transfer and
  review, and initiates review.

The operator does not make editorial or retention decisions. A person or
system may perform more than one role operationally, but the responsibilities
remain distinct.

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
├── package.sha256
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

`package.json` is the authoritative inventory of every other handoff artifact
except `package.sha256`, which is excluded to avoid circular self-reference.
The manifest contains:

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
inventory, the failed run outcome produces a run receipt or diagnostic result
rather than a conforming source package. Item-level
failures remain valid inside a `completed_with_errors` sealed package.

### Package Integrity

A sealed package is immutable. `package.json` is the authoritative manifest and
inventories every other handoff artifact except `package.sha256`.
`package.sha256` is the external manifest digest: it contains exactly 64
lowercase hexadecimal characters representing the SHA-256 digest of the exact
stored bytes of `package.json`, followed by one newline. No other sidecar format
is valid. The package content address is the SHA-256 digest recorded in
`package.sha256`.

The digest applies to the exact stored `package.json` bytes. Encoding, line
endings, whitespace, key order, and every other byte-level choice are therefore
significant. Verification must not hash a reparsed, reformatted, reserialized,
or otherwise canonicalized JSON representation.

After the external manifest digest is verified, the manifest inventory must
cover every other handoff artifact, and every inventoried artifact must match
its recorded byte size and required SHA-256 digest. The manifest supplies the
package identity, contract version, terminal accounting, and minimum review
lineage needed to interpret that inventory. A package is self-contained without
external runtime state.

These digests provide package integrity and content addressing: they allow a
consumer to detect changes to the manifest and its inventoried bytes. Replacing
both `package.json` and `package.sha256` remains possible without an
authenticated external channel or signature. The adapter identity recorded in
the manifest is provenance. Neither matching digests nor a claimed adapter
identity establishes producer authenticity or trust. Authenticated producer
identity is outside the v1 contract. A future authenticated-package capability
may build on the verified manifest digest without changing package semantics;
this document does not define signatures or cryptographic authentication.

Consumers may copy or quarantine a package but must not edit it in place.
Corrections produce a new package with lineage to the superseded package.

### Consumer Verification Order

A consumer must verify a package in this order:

1. Confirm `package.json` and `package.sha256` exist and meet consumer-defined
   size limits, and confirm `package.sha256` has the required format.
2. Compute SHA-256 over the exact stored bytes of `package.json`.
3. Compare the computed digest with the lowercase hexadecimal digest in
   `package.sha256`.
4. Parse and validate `package.json`.
5. Verify contract name, version, required capabilities, identities, terminal
   accounting, and path safety.
6. Verify the exact byte size and SHA-256 digest of every artifact inventoried
   by the manifest.
7. Only then allow the package to proceed to content review.

A missing, malformed, or mismatched `package.sha256` causes structural
rejection before content inspection. A consumer must not rely on any field in
`package.json` until the external manifest digest matches.

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
state. `package.json` is authoritative and must contain the minimum lineage
required by every consumer: `resumes_run_id` when applicable, prior package or
run identifiers, a reconciliation summary, and final attempt counts. An
optional sealed `run-receipt.json` may carry supplemental execution history but
cannot override the manifest. Consumers must not require the optional receipt
to understand package identity, compatibility, or review lineage. The package
remains self-contained and verifiable after adapter-local checkpoints and
provider cursors are deleted.

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

SHA-256 is the required package digest algorithm for v1. Future algorithm
agility may be introduced only through a later contract revision.

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
  external manifest digest, terminal accounting, redaction, and partial
  failure;
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
├── package.sha256
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

`package.sha256`:

```text
<64-lowercase-hex-sha256-of-exact-package.json-bytes>
```

This placeholder is non-normative. A conforming package contains the actual
64-character lowercase hexadecimal digest followed by one newline.

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

Authenticated producer identity and authenticated packages remain an explicit
future capability. Any later capability should build on the existing manifest
digest without changing the meaning of package contents or lifecycle.

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
4. Which supplemental execution details, if any, are useful in the optional
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

1. Ratify the canonical Source Package Contract in `knowledge-adapters` and
   validate the `knowledge-vault` consumer profile against it.
2. Add producer conformance validation and package sealing in
   `knowledge-adapters`, without a provider migration.
3. Add vault-side quarantine validation and review-record linkage against
   fixtures.
4. Migrate one bounded adapter and one vault review example end to end.
5. Add checkpoint/resume and partial-failure conformance tests.
6. Migrate additional adapters incrementally; promote common fields only from
   demonstrated cross-provider needs.
