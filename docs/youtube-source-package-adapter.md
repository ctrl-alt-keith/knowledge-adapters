# YouTube Source Package Adapter

Status: deterministic Wave 2 producer; live pilot not executed.

## Boundary And Configuration

The adapter accepts only explicit HTTPS YouTube video or playlist locators. A
resource request has `max_items=1`; a collection request requires a positive
`max_items`. Optional `batch_size` cannot exceed that collection bound.
Language preference order, base-language fallback, caption policy, no-caption
outcome, raw-caption retention, checkpoint paths, and retry attempts are typed
and recorded in the canonical `AcquisitionRequest`.

`yt-dlp` is isolated behind `YouTubeClient` and is available only through the
`youtube` optional dependency group. The embedded client supplies explicit
options, requests no media download or postprocessing, permits no remote
components, and consumes caption URLs only inside the client boundary. It does
not require ffmpeg. Adapter identity records both the adapter version and
observed yt-dlp version. Tests use `FakeClient`; `make check` neither imports
yt-dlp nor accesses a provider.

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

Provider failures enter the producer as structured categories. Private,
removed, age-restricted, geo-restricted, unavailable, timeout, throttling,
transient, and cancellation observations map to bounded item errors. Timeout,
HTTP 429, and HTTP 5xx evidence is retryable within `max_attempts`; other
unknown yt-dlp exceptions conservatively map to non-retryable unavailable
without classifying from message text. Private and other access classifications
are used only when yt-dlp exposes structured availability evidence; unsupported
or absent evidence remains `provider-unavailable`. No captions is `skipped` or
`failed` according to the effective request.

Checkpoint JSON is mutable adapter-local state and is never inventoried. It is
bounded and versioned and records a request fingerprint, adapter and contract
versions, playlist identity, discovery IDs, completed IDs and digests,
outcomes, attempts, pending IDs, continuation evidence, and last successful
boundary. Resume validates schema, fingerprint, adapter version, and contract
version, then reconciles rediscovery by video ID. A raw yt-dlp archive is not a
canonical checkpoint.

## Collection Progress Gate

Contract/core `1.0.0` cannot unambiguously seal partial or resumed collections.
`AcquisitionRequest.scope.max_items` records requested intent, but not whether
the observed bounded scope was exhausted or continuation remains. The public
`PackageBuilder` reserves resume-lineage fields but exposes no way to populate
them, and public verified claims expose neither request scope nor a collection
progress value.

Therefore this adapter seals only:

- one fully processed video; or
- a fully processed bounded playlist observation.

If bounded discovery reports continuation inside the requested window, or
`batch_size` leaves selected items pending, the adapter may write a checkpoint
but raises `CollectionProgressBlocked` before creating a package. Resume state
is validated but cannot be sealed until the canonical core exposes
provider-neutral progress and lineage. Progress is not hidden in the YouTube
extension.

The embedded client passes `playlistend=max_items`; therefore its `exhausted`
observation means discovery completed the requested bounded window, not that
the provider playlist has no later members. A smaller `batch_size` is the
explicit continuation-within-that-bound case. Its checkpoint records completed
item digests and leaves the rest pending, but no partial package is sealed.

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
