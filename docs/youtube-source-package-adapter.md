# YouTube Source Package Adapter

Status: deterministic Wave 2 producer; live pilot not executed.

## Boundary And Configuration

The adapter accepts only explicit HTTPS YouTube video or playlist locators. A
resource request has `max_items=1`; a collection request requires a positive
`max_items`. Optional `batch_size` cannot exceed that collection bound.
Language preference order, base-language fallback, caption policy, no-caption
outcome, raw-caption retention, checkpoint paths, and retry attempts are typed
and recorded in the canonical `AcquisitionRequest`.

Explicit v1 bounds are at most 500 collection items, 16 language preferences,
64 relevant caption candidates per video, 8 MiB per captured caption, and 4096
UTF-8 bytes per consumed provider metadata string. Playlist and candidate data
must have the expected shallow dict/list/scalar shape. The client downloads
only the selected VTT candidate with a `limit + 1` read; excess candidates or
bytes fail before normalization.

`yt-dlp` is isolated behind `YouTubeClient` and is available only through the
`youtube` optional dependency group. The embedded client supplies explicit
options, requests no media download or postprocessing, permits no remote
components, and consumes caption URLs only inside the client boundary. It does
not require ffmpeg. Canonical adapter identity records the adapter version and
caller-supplied build revision. The separate YouTube extension records the
observed yt-dlp version; it is not represented as the adapter revision. Tests
use `FakeClient`; `make check` neither imports yt-dlp nor accesses a provider.

The live boundary follows yt-dlp's official documentation for
[`--ignore-config`, `--flat-playlist`, `--skip-download`, and creator versus
automatic subtitle options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md).
The Python API receives parameters directly rather than invoking the CLI config
loader. This source was checked on 2026-07-10. yt-dlp does not guarantee that
`extract_info` returns JSON-serializable data, so the client copies only a
small typed observation surface.

## Identity, Selection, And Normalization

Video IDs and playlist IDs are provider identities. Video item IDs are
`youtube-video-<video-id>`. Canonical locators omit playlist context, tracking
parameters, caption URLs, and other expiring query data. Playlist membership is
parent provenance; observed positions remain YouTube-namespaced evidence.
Duplicate positions sort by video ID and missing positions sort after observed
positions. The canonical builder subsequently applies its own stable item-ID
inventory ordering.

Caption selection is deterministic:

1. match ordered language preferences exactly, with base-language fallback
   only when explicitly enabled;
2. `creator-only` excludes automatic tracks;
3. `creator-then-automatic` considers all preferred creator tracks before
   automatic tracks;
4. `automatic-allowed` applies language rank first, then prefers creator over
   automatic within the same language rank.

Candidate summaries contain language, kind, format, and an optional stable
name. They never contain caption URLs.

Normalizer `youtube-webvtt-to-markdown/1.0.0` decodes UTF-8 strictly,
normalizes CRLF/CR to LF and Unicode to NFC, removes the WebVTT transport
header and cue timestamps, converts WebVTT voice labels to bold Markdown
speaker labels, strips remaining tags, collapses rolling automatic-caption
cues, preserves spoken cue order, and emits exactly one trailing newline.
Malformed WebVTT and unsupported formats fail deterministically. Raw WebVTT is
omitted unless explicitly retained.

## Failure And Checkpoint Semantics

Provider failures enter the producer as structured categories. Fixture-backed
contract mapping covers private, removed, age-restricted, geo-restricted,
unavailable, timeout, throttling, transient, and cancellation outcomes. This
does not claim yt-dlp supplies structured evidence for every category. The real
boundary maps only explicit availability, status, or exception attributes it
observes. Timeout, HTTP 429, and HTTP 5xx evidence is retryable within
`max_attempts`; other
unknown yt-dlp exceptions conservatively map to non-retryable unavailable
without classifying from message text. Private and other access classifications
are used only when yt-dlp exposes structured availability evidence; unsupported
or absent evidence remains `provider-unavailable`. No captions is `skipped` or
`failed` according to the effective request.

Checkpoint JSON is mutable adapter-local state and is never inventoried. JSON
is limited to 1 MiB, depth 8, and the 500-item collection bound. It is versioned
and records a request fingerprint, adapter and contract
versions, playlist identity, discovery IDs, completed IDs and digests,
outcomes, attempts, pending IDs, continuation evidence, and last successful
boundary. Checkpoint schema 1.3 also stores the bounded typed identity,
locator, observed metadata, caption selection, collection relationship, run,
package, and prior-lineage fields required to reconstruct preserved completed
items without copying a manifest model. `retain_raw_captions` governs every
durable adapter-managed surface. When false, raw caption bytes are omitted from
the package, checkpoint, diagnostics, receipts, and logs; completed checkpoints
retain only normalized bytes, digests, bounded selected-track metadata,
normalization provenance, and structural resume state. When explicitly true,
the checkpoint may retain raw bytes so resume can preserve the opted-in package
artifact without reacquisition.

Resume validates schema, fingerprint, adapter version, contract version, and
retention mode, then reconciles rediscovery by video ID. Completed bytes live under
checkpoint-owned relative paths in `<checkpoint-stem>.data/`; regular-file,
path, 8 MiB, and SHA-256 checks run on load. Resume copies only matching
verified bytes into the next checkpoint, drops disappeared IDs, and marks new
IDs pending. Attempt counts are cumulative across checkpoints while the retry
limit applies independently to the new run, so failure-to-success transitions
record the additional attempt. The attempts map contains only identities that
have actually been attempted, and every stored count is positive;
never-attempted pending identities are omitted rather than recorded with zero.
A raw yt-dlp archive is not a canonical checkpoint. Schema 1.2 checkpoints are
rejected rather than silently migrated,
preventing legacy raw-caption state from crossing a disabled-retention boundary.
Work interrupted before successful normalization is not completed and is
reacquired on resume.

## Canonical Collection Progress And Resume

Collection packages use contract 1.1 and the public `CollectionProgress` and
`PackageLineage` models. A batch that leaves entries inside the requested bound
seals with `continuation_remaining`. A run that terminally accounts for the
entire bounded window seals with `exhausted`; this does not claim the provider's
global playlist has no later entries.

On resume, the adapter rediscovers the original bounded window, reuses only
matching video IDs with verified cached bytes, assigns `unchanged` to those
preserved package items, acquires the next bounded batch, and records the prior
run/package IDs, cumulative attempts, and reconciliation counts through public
`PackageLineage`. Disappeared IDs are counted as dropped and new IDs become
pending or acquired according to the batch boundary.

The producer verifies with an explicit public `ConsumerProfile` supporting the
collection-progress capability. Handoff assertions use only public verified
package, item-disposition, artifact-inventory, totals, progress, and lineage
summaries. Provider extensions and content bytes are not read back or treated
as verifier claims.

The embedded client passes `playlistend=max_items`, so normal live discovery is
complete relative to that window. `batch_size < max_items` is the actionable
continuation case. A provider observation that says the window is not exhausted
after every returned entry was attempted cannot advance through this adapter's
safe rediscovery convention; it is explicitly blocked instead of emitting an
endlessly resumable checkpoint or using an undocumented cursor.

## Prepared Live Pilot (Not Executed)

After deterministic producer-to-consumer integration passes and an operator
explicitly authorizes live access, use a new disposable output directory and
an explicit playlist locator with `max_items=3`, `batch_size=3`, bounded retry
attempts, creator-then-automatic captions, ordered languages, base-language
fallback disabled, and raw-caption retention disabled. Record the installed
yt-dlp version, verify the sealed package through the public verifier, inspect
only the bounded package for signed URLs or secrets, and hand the unchanged
bytes to vault quarantine. Do not enumerate the full Running Remote playlist,
auto-promote content, or treat a successful canary as conformance evidence.
