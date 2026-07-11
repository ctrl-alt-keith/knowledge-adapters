# YouTube Source Package Implementation Plan

Status: Wave 1 implementation plan. Provider code and live acquisition are out of scope.

## Goal And Boundaries

Add a reusable YouTube producer for individual videos and playlists that emits the canonical Source Package defined by [`source-package-contract.md`](source-package-contract.md). The provider module will acquire and normalize; the shared Source Package library will own interchange models, sealing, inventory, hashing, and verification. This plan must not introduce a parallel manifest model.

The Running Remote playlist (`PL0jNebZFYUQ_5ZNRNbMOBeKzAmrBJC3gW`) is only the motivating pilot. Wave 1 does not enumerate or download it. A later pilot will select two or three representative videos after inspecting the collection with a bounded item limit.

## Proposed Module Layout

```text
src/knowledge_adapters/youtube/
  __init__.py       public request/result surface
  config.py         provider options and validation
  client.py         yt-dlp boundary and error translation
  models.py         adapter-local discovery/caption/checkpoint records
  resolve.py        video/playlist locator resolution
  captions.py       track selection and captured-caption parsing
  normalize.py      deterministic transcript-to-Markdown transform
  checkpoint.py     mutable, adapter-local resume state
  producer.py       bounded orchestration into the shared package builder
tests/youtube/
tests/fixtures/youtube/
```

The module should follow the repository's proven source-specific organization, but its `producer.py` should target the Source Package builder rather than the older adapter manifest/writer shape. Shared helpers should be extracted only after a second Source Package producer proves a common seam.

## Public Adapter Behavior

The initial public call should construct the shared typed `AcquisitionRequest`
from common request fields plus namespaced YouTube extensions, then return
either a sealed package result or a failed-run diagnostic/receipt result. The
typed request, rather than provider code, owns `request.json`. It should support:

- `scope.kind = resource` for one video and `scope.kind = collection` for one playlist;
- a mandatory positive collection bound (`max_items`) and an optional per-run `batch_size`;
- ordered language preferences and explicit caption policy (`creator-only`, `creator-then-automatic`, or `automatic-allowed`);
- optional checkpoint input/output outside the sealed package;
- explicit no-caption behavior, without silently falling back to audio transcription;
- one item, a bounded playlist batch, or a resumed collection using the same producer API.

Configuration must reject unbounded playlist acquisition, secrets embedded in locators, unsupported URL families, nonpositive limits, and ambiguous language policy before writing package artifacts.

## Provider Tool Boundary

Use `yt-dlp` behind a narrow client protocol. Prefer the Python package for structured `extract_info` results and typed exception translation, pinned to a tested compatible release range in an optional `youtube` dependency group. Do not add it to core dependencies until implementation evidence confirms the embedding surface is stable enough. Record the detected yt-dlp version/build in adapter identity.

The CLI executable may be supported later as an alternate backend, but deterministic tests must use a fake client and sanitized recorded payloads. Disable ambient yt-dlp configuration and remote components so operator-global config cannot silently change acquisition. `ffmpeg` is not required for caption-only v1. The official yt-dlp documentation distinguishes creator subtitles from automatic subtitles, supports language selection, bounded playlist item selection, flat playlist discovery, and archive-based resume; these features are provider observations, not interchange semantics. Checked 2026-07-10: <https://github.com/yt-dlp/yt-dlp/blob/master/README.md>.

## Identity And Locator Semantics

- Provider identity is the YouTube video ID for video items and playlist ID for the collection observation. Package `item_id` should be a deterministic, path-safe encoding such as `youtube-video-<video-id>`; it must not depend on title or playlist position.
- `requested_locator` is exactly the caller's non-secret locator after safe syntactic normalization.
- `resolved_locator` records the provider-resolved watch or playlist URL returned by the client.
- `canonical_locator` is `https://www.youtube.com/watch?v=<video-id>` for a video and `https://www.youtube.com/playlist?list=<playlist-id>` for collection provenance. Remove tracking and playlist-context query parameters from a video's canonical locator.
- A playlist is acquisition scope and parent provenance, not a replacement video identity. Each video item records the collection ID and observed source position in the YouTube namespaced extension. The same video in multiple collections retains its video identity while relationship observations remain run-specific.
- Preserve provider order explicitly as `source_position`; package item ordering should follow the request target order and then the observed playlist order, with stable video ID as the deterministic tie-breaker for malformed duplicate positions.

Do not use title, uploader name, signed media URLs, caption URLs, or playlist index as canonical identity. Flat playlist metadata can be incomplete, so discovery identities must be enriched per selected video before sealing.

## Caption Selection And Provenance

Treat creator captions and automatic captions as different representations. Select deterministically:

1. walk the caller's ordered language preferences using exact BCP-47-like tags first, then explicitly configured base-language fallback;
2. choose a creator track when permitted and present;
3. choose an automatic track only when policy permits and no preferred creator track was selected;
4. exclude live chat and unrelated subtitle-like tracks;
5. record all observed candidates and the selection reason in `extensions["org.ctrl-alt-keith.youtube"]`.

The item record reports language as observed, caption kind (`creator` or `automatic`), track identifier/name, source format, and yt-dlp observation fields that are safe and stable enough for provenance. Absence is not invented. A video with no eligible captions is terminal `skipped` with a structured `captions-unavailable` reason unless the request explicitly defines missing captions as a failed requirement; that policy must be recorded in the effective request.

Raw caption bytes are the captured form. They may be inventoried as an optional quarantined artifact when explicitly requested; normalized Markdown is the baseline candidate artifact. Expiring caption download URLs never enter the package.

## Normalization Boundary

Normalization begins from captured subtitle bytes, not live yt-dlp metadata. The deterministic normalizer will:

- decode only declared/supported UTF-8 caption formats in v1 (prefer WebVTT; add JSON3 only with fixtures);
- remove transport headers and duplicate rolling automatic-caption cues;
- normalize line endings to LF and Unicode to a documented form;
- preserve spoken text order and meaningful speaker labels;
- apply a declared timestamp policy consistently;
- emit deterministic UTF-8 Markdown with one trailing newline;
- disclose every transformation and a version in the item record.

Given the same captured bytes, config, normalizer version, and contract version, output bytes must match. Provider retrieval time, playlist order changes, retries, and signed URLs cannot affect normalized bytes.

## Source Package Mapping

| YouTube observation | Canonical package field/artifact |
| --- | --- |
| Video ID | provider resource identity and stable `item_id` |
| Playlist ID and position | parent/collection relationship plus namespaced extension |
| Input URL | `requested_locator` |
| Extracted webpage URL | `resolved_locator` |
| Stable watch URL | `canonical_locator` |
| Title/channel/upload timestamp | common observed metadata when present |
| Caption language and kind | item language plus namespaced provenance |
| Captured caption bytes | captured digest; optional quarantined raw artifact |
| Normalized transcript | `normalized-content` Markdown artifact |
| Extraction/caption failure | item error/skip and diagnostic artifact |
| yt-dlp release | adapter build/revision identity |

The producer supplies item records, candidate artifacts, diagnostics, and
namespaced extensions through Lane A's public builder. It must not write
`request.json`, `package.json`, `package.sha256`, inventory digests, counts,
identity, lifecycle, or receipt lineage itself. Provider extensions live under
`org.ctrl-alt-keith.youtube`; the builder rejects attempts to override canonical
fields. Package-level status derives from terminal items. After sealing, the
producer invokes only the public verifier and hands off a package only when its
overall state is `verified`. Handoff checks use the content address and curated
verified claims; the adapter does not depend on receiving its complete manifest
back from verification.

YouTube-specific extensions remain inventoried package content and are not
promoted into public verification-result claims. Any provider-specific
inspection after structural verification is a separate, explicitly bounded
path and cannot change the verifier result. Collection-progress meaning stays
in the canonical request/lineage/limitation model below and is never hidden in
curated verifier claims.

## Checkpoint, Batching, And Resume

Checkpoint state is mutable and adapter-local, never inventoried. It should contain schema version, request fingerprint, contract and adapter versions, playlist ID, discovery observation, next source position/cursor when safe, completed video IDs with captured/normalized digests, terminal outcomes, attempt counts, pending IDs, and the last successful boundary.

Because playlist membership and order can change, a raw yt-dlp archive is
insufficient as the canonical checkpoint. On resume, rediscover within the
requested bound unless a documented provider cursor is proven safe, reconcile
by video ID, verify saved artifact digests, preserve matching completed work,
and start a new `run_id` with builder-owned manifest lineage. `batch_size`
limits attempted items in one run; `max_items` limits total collection scope.

The shared representation is contract 1.1 `CollectionProgress`: record the
bounded scope and batch limit in the typed request, then record either
`exhausted` or `continuation_remaining` in the package-level progress field.
Use `PackageLineage.resumes_run_id` and the remaining canonical lineage fields
for resumed work. The builder adds the required `collection-progress`
capability, and producer verification must opt into that capability. Provider
extensions may preserve YouTube cursor evidence but cannot carry the only
meaning of collection completeness.

## Failure Mapping

Provider errors must be translated at the client boundary and retain sanitized diagnostics:

| Condition | Default item result | Retry posture |
| --- | --- | --- |
| No eligible captions | `skipped` / `captions-unavailable` | permanent for this observation |
| Removed or deleted video | `failed` / `provider-removed` | permanent |
| Private video without access | `failed` / `access-denied` | operator action, not automatic |
| Age restriction | `failed` / `access-restricted` | operator/config action |
| Geo restriction | `failed` / `geo-restricted` | permanent for current execution context |
| Playlist member unavailable | `failed` / `provider-unavailable` | classify from evidence; bounded retry only if transient |
| Throttling, timeout, 5xx | `failed` after attempts / `provider-transient` | bounded retry |
| Unsupported caption format | `failed` / `normalization-unsupported` | deterministic, no retry |
| Invalid locator or request | failed run before package sealing | no retry |
| Operator cancellation | `cancelled` | no automatic retry |

Do not infer private/removed/geo/age categories from message text alone when structured extractor evidence exists. Keep a conservative `provider-unavailable` fallback and preserve a redacted diagnostic code. Exact yt-dlp exception mapping should be proven against fixtures before becoming public behavior.

## Deterministic Fixture Plan

Create sanitized, hand-auditable fixtures rather than captured full provider pages:

- single video with creator English WebVTT;
- creator and automatic tracks with language precedence;
- automatic-only captions with rolling duplicate cues;
- missing captions;
- playlist with three entries, duplicate/missing positions, and one unavailable entry;
- private, removed, age-restricted, geo-restricted, timeout, and throttling client results;
- malformed WebVTT and unsupported caption format;
- interrupted batch and changed playlist on resume;
- raw-caption opt-in versus default omission;
- stable package mapping assertions through Lane A's public API and Lane B conformance verification.

Fixtures should assert exact normalized bytes, item order, provider-neutral outcomes, namespaced extensions, no signed URLs/secrets, and deterministic replay. They must not require network, credentials, yt-dlp, or ffmpeg during `make check`.

Sealing tests must also simulate a failed write or final placement, confirm the
collision-resistant temporary tree is removed, retry successfully without
modifying an existing destination, and verify the result through the public
verifier.

## Optional Live Canary

Keep a separately invoked, nonblocking canary outside `make check`. It may inspect one explicitly configured public video with a strict timeout and no credentials, report yt-dlp version, available caption classes/languages, and whether deterministic normalization succeeds. It must not publish captured content, mutate fixtures automatically, or establish contract conformance. Live playlist enumeration requires an explicit operator-provided small bound.

## Phased Commits

1. Add optional dependency policy, adapter-local models/config, locator parsing, and fake client protocol.
2. Add caption selection plus deterministic WebVTT normalization with fixtures.
3. Add video acquisition and Source Package builder mapping through Lane A's merged public API.
4. Add bounded playlist discovery, terminal accounting, and failure translation.
5. Add checkpoint verification, batching, resume reconciliation, and lineage tests.
6. Add CLI/config wiring, deterministic integration tests, docs, and optional live-canary command.

Each commit should run `make check`. The Source Package core PR must merge before commit 3 is based or implemented; conformance fixtures should validate the produced package without importing provider internals.

## Running Remote Pilot Acceptance

After implementation and explicit live-test approval, select two or three entries within a bounded discovery window: one with creator captions, one automatic-caption case if present, and one unavailable/missing-caption case if present. If the collection does not contain all categories, use the available cases and retain deterministic fixtures for the missing categories.

The pilot passes when it:

- never enumerates or downloads the full playlist implicitly;
- seals a conforming package verified by the canonical verifier and Lane B cases;
- produces deterministic normalized transcript bytes on fixture replay;
- preserves video and collection identities and caption provenance;
- accounts for every selected item with a terminal outcome;
- resumes an interrupted bounded batch without changing prior matching outputs;
- excludes credentials, cookies, signed caption URLs, and raw captions by default;
- reports live-provider observations separately from deterministic validation.

## Cross-PR Dependencies And Open Questions

- **Lane A:** provide a public builder that accepts artifact bytes/paths, item records, namespaced extensions, diagnostics, and optional receipt data without exposing sealing internals. Structured results need stable machine-readable issue codes and field/path context.
- **Lane A result boundary:** producer handoff consumes result state, stage,
  findings, content address, and curated verified claims only; raw manifest and
  provider extensions are not result fields.
- **Lane B:** verify provider-produced packages only through the public verifier; share package-level fixtures, not YouTube client fixtures.
- **Consumer:** no YouTube-specific fields should be required for baseline review; the normalized artifact and common provenance must be sufficient.
- Does the contract need an explicit collection item record, or is a parent identity in each video record plus request scope sufficient?
- Collection progress is resolved by contract 1.1: a sealed bounded batch uses
  `collection_progress.state=continuation_remaining`; exhaustion uses
  `exhausted`; resume remains canonical lineage rather than a progress state.
- Should no eligible captions default to `skipped` or `failed` when transcript acquisition is the request's primary intent? The effective request should choose; the contract may need clearer guidance.
- Which caption timestamp policy best supports review while keeping normalized output stable?
- Which yt-dlp structured exceptions and fields remain stable enough for supported error categories? Decide from implementation fixtures and official release evidence.
- Does raw-caption retention require a standard artifact role, or is an optional provider-namespaced role sufficient for v1 consumers to ignore safely?
- Should the first release embed yt-dlp or invoke a pinned executable? Benchmark packaging, exception stability, update cadence, and ambient-config isolation before deciding.
- Audio transcription remains a later, separately declared capability with its own media acquisition, resource limits, provenance, and model/version disclosures; it must never be an implicit caption fallback.
