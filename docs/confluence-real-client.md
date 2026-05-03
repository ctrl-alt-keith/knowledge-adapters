# Confluence Real Client Design

## Purpose

This document defines a minimal v1 design for introducing a real Confluence client path as an explicit opt-in alternative to the current default stub client.

The goal is to enable fetching real page data for the existing single-page pipeline without changing the current default behavior or forcing downstream layers to absorb client or auth concerns.

## Scope

v1 covers only:

- keeping the current stub client as the default CLI behavior
- adding an explicit real-client mode for live page fetches
- fetching one Confluence page by canonical page ID
- returning only the page fields already needed by the existing normalization and writing pipeline
- isolating auth/config handling so future auth modes can be added without changing traversal, manifest, or writer contracts

v1 does not make the real client the default.

## Existing Baseline

Today the Confluence adapter already has the following shape:

- CLI resolves `--target` into a canonical page ID
- CLI calls one client-layer fetch function
- normalization expects a page payload with `canonical_id`, `title`, `content`, and `source_url`
- traversal, deduplication, manifest handling, and writing are already separate layers
- the default client is a stub and does not contact Confluence

This design keeps those boundaries intact.

## Design Summary

The adapter should support two client modes:

- `stub`: the existing default behavior, unchanged
- `real`: an explicit opt-in path that performs a live Confluence fetch for one canonical page ID

The CLI remains responsible for runtime selection and top-level error reporting. The client layer remains responsible only for fetching and returning page data. Auth remains isolated behind a small auth/config boundary used only by the real client.

## Client Mode Strategy

### CLI selection

Add a new CLI/config field:

- `--client-mode {stub,real}`
- default: `stub`

Selection rules:

- if `--client-mode` is omitted, behavior remains the current stub flow
- `--client-mode stub` forces the current stub behavior even when real-client auth settings are present
- `--client-mode real` opts into the live fetch path

This keeps the migration safe because all existing commands continue to use the stub client unless the caller explicitly asks for the real client.

### Config shape

The runtime config should distinguish:

- client selection: `client_mode`
- auth selection for real mode: `auth_method`
- fetch inputs: `base_url`, resolved canonical page ID

The CLI should build one config object and pass it into client selection logic rather than teaching writers, traversal, or manifest code about stub-vs-real behavior.

### Safe migration path

The migration is intentionally non-breaking:

- existing CLI invocations continue to succeed unchanged
- existing tests that rely on stub behavior continue to use the default mode
- real-client tests are additive and explicit
- making the real client the default would require a later, separate design change

## v1 Supported Behavior

### Supported fetch operation

The real client v1 supports exactly one live operation:

- fetch a single page by canonical page ID after the existing target-resolution step

The real client does not perform title lookup, search, traversal, writing, manifest updates, or deduplication.

### Returned page payload

The real client should return the same adapter-level payload shape the existing pipeline already expects:

- `canonical_id`: required string
- `title`: required string
- `content`: required string
- `source_url`: required string

Field mapping rules for v1:

- `canonical_id` is the canonical page ID returned by Confluence and must match the resolved page ID used for the request
- `title` is the page title from the Confluence response
- `content` is the single body field used by normalization in v1
- `source_url` is required in v1 and must be the canonical absolute web URL for the page
- when the selected Confluence response shape provides enough data to construct `source_url`, the client should construct it as an absolute URL
- if the response does not provide enough data to construct the required `source_url`, the client must treat that response as invalid for v1

### Body/content choice

v1 should choose one Confluence body representation and expose it through the existing `content` field.

Recommended v1 choice:

- use the Confluence storage-body value as `content`

Why this is the right v1 choice:

- it is a single string field that matches the current normalization contract
- it avoids forcing the normalizer to understand multiple Confluence body formats
- it leaves room for future format expansion behind the client boundary

### Child-page discovery surface

Real tree traversal uses a separate client function for child discovery rather than
overloading the page payload.

v1 rules:

- `fetch_real_page(...)` continues to return one page payload
- `list_real_child_page_ids(...)` returns only direct canonical child page IDs
- traversal behavior, deduplication, ordering, and depth handling remain outside
  the client

### Interaction with tree mode

`--client-mode real` supports tree traversal through the existing traversal layer.

The real client remains responsible only for:

- fetching one page by canonical page ID
- listing one page's direct child page IDs

Tree semantics are defined separately in
[`docs/confluence-real-traversal.md`](./confluence-real-traversal.md).

## Auth Design

### v1 auth mode

v1 supports these real auth modes:

- `bearer-env`
- `client-cert-env`

Behavior:

- `bearer-env` reads a bearer token from `CONFLUENCE_BEARER_TOKEN`
- `bearer-env` builds the `Authorization: Bearer ...` header for the request
- `client-cert-env` reads a client certificate from `CONFLUENCE_CLIENT_CERT_FILE`
- `client-cert-env` optionally reads a separate private key from
  `CONFLUENCE_CLIENT_KEY_FILE`
- when `CONFLUENCE_CLIENT_KEY_FILE` is omitted, `CONFLUENCE_CLIENT_CERT_FILE`
  may point to a combined PEM file
- if required auth material is missing or empty, the run fails before any request
  is made
- invalid certificate material fails before any request with a small config error;
  v1 does not attempt advanced key handling or live certificate validation

The existing `auth_method` field continues to name the selected auth strategy for
real mode.

### Auth boundary

Auth should remain isolated behind a small helper boundary, for example:

- validate auth config for the selected `auth_method`
- resolve secrets from the environment
- build request headers or other request auth material for the real client

The fetch client should consume that auth material, not know how credentials are sourced.

This keeps future auth growth localized to config/auth modules instead of spilling into:

- CLI traversal logic
- manifest logic
- incremental sync rules
- writer behavior

### Deferred future auth modes

The following auth work beyond minimal environment-driven `bearer-env` and
`client-cert-env` support is explicitly deferred:

- broader auth abstractions or multi-provider auth systems
- advanced certificate handling such as passphrase-protected keys
- enterprise-specific auth combinations beyond `bearer-env` and
  `client-cert-env`
- OAuth variants
- cookie/session-based auth
- other runtime-specific enterprise auth mechanisms

Future auth modes should extend the auth/config boundary only. They must not require traversal, writing, deduplication, or manifest logic to change.

## Integration Boundaries

### Responsibilities that stay in the client

The real client is responsible only for:

- making the live request
- validating the source response shape
- mapping the source response into the adapter page payload

### Responsibilities that stay outside the client

The following remain in their current layers:

- target resolution
- tree traversal
- deduplication by canonical page ID
- dry-run planning
- manifest handling
- file writing
- incremental skip logic

The CLI should select the client mode and surface high-level errors, but it should not absorb response parsing or auth construction logic.

## Error Behavior

v1 should use fail-fast behavior with small, testable error categories surfaced by the real client.
Confluence REST uses standard HTTP status codes and can return `429` with
`Retry-After` for rate limits; see Atlassian's Confluence REST API reference and
rate limiting guidance:

- https://developer.atlassian.com/cloud/confluence/rest/v1/intro/
- https://developer.atlassian.com/cloud/confluence/rate-limiting/

The CLI keeps the existing concise error message and adds a stable
`failure_class` detail line for classified real-client failures:

- `auth`: authentication or authorization failure, including Confluence `401`
  or `403`
- `configuration`: missing or invalid local auth, TLS, or client certificate
  inputs
- `expected_retryable`: rate limiting, network timeouts, connection failures, or
  other transport failures that operators may retry after the cause clears
- `permanent`: not-found responses or malformed response payloads that should
  not be retried without changing inputs or adapter behavior
- `provider`: Confluence `5xx` provider-side failures

### Auth failure

Cases:

- bearer token missing before request
- Confluence returns `401` or `403`

Behavior:

- fail the run
- do not write files
- do not write or replace `manifest.json`

Failure class:

- `auth`, except missing local credential material is `configuration`

### Page not found

Case:

- Confluence returns `404` for the requested canonical page ID

Behavior:

- fail the run
- do not write files
- do not write or replace `manifest.json`

Failure class:

- `permanent`

### Malformed or unexpected response shape

Cases:

- missing page ID, title, body field, or link data needed for `source_url`
- non-string body/title values where strings are required
- missing or insufficient URL/link data to construct the required absolute `source_url`
- response page ID does not match the requested canonical page ID

Behavior:

- fail the run
- do not attempt partial normalization
- do not write files
- do not write or replace `manifest.json`

Failure class:

- `permanent`

### Child-page discovery failure

Child-page discovery is not part of real-client v1.

If a future implementation starts populating `children`, any failure to retrieve or validate that child listing should also fail the run rather than silently dropping descendants.

## Testing Strategy

### Required CI coverage

`make check` must not require live Confluence access.

v1 test coverage should rely on mocked or fixture-based tests for:

- CLI mode selection: default stub vs explicit real mode
- auth config validation for `bearer-env` and `client-cert-env`
- request construction for the real client
- response-to-payload mapping
- error mapping and classification for `401/403`, `404`, `429`, `5xx`,
  transport failures, and malformed response bodies
- rejection of unsupported real-mode tree usage

### Preferred test style

Prefer tests at two layers:

- parser/mapping tests with canned Confluence JSON payloads
- client tests with mocked HTTP responses

This keeps CI deterministic and avoids coupling `make check` to network access or live credentials.

### Live validation

Optional manual validation may exist outside normal repository validation, for example:

- developer-run command with `--client-mode real`
- real `--base-url`
- real bearer token in `CONFLUENCE_BEARER_TOKEN`
- real client certificate material in `CONFLUENCE_CLIENT_CERT_FILE` and optional
  `CONFLUENCE_CLIENT_KEY_FILE`

That live check is opt-in only and is not part of `make check`.
Repository validation covers mocked contract behavior only; it does not prove a
real certificate handshake against a live Confluence deployment.

## Out of Scope

The following are explicitly out of scope for v1:

- making the real client the default
- live enterprise auth beyond `bearer-env` and `client-cert-env`
- broader auth abstractions or multi-provider auth systems
- attachments
- comments
- adaptive rate-limit sophistication beyond explicit operator pacing
- macro fidelity improvements
- write-path refactors
- manifest schema changes
- incremental sync contract changes
- broad client-layer refactors unrelated to stub-vs-real selection

## Acceptance Criteria

The implementation guided by this design should support tests that verify at least:

- default CLI behavior still uses the stub client when `--client-mode` is omitted
- explicit `--client-mode real` uses the real client path
- real mode fetches one page by canonical page ID and returns adapter payload fields required by the current pipeline
- real mode keeps page fetch and child discovery as separate client responsibilities
- auth failures, not found responses, and malformed responses fail fast without writing artifacts
- future auth additions can be implemented inside the auth/config boundary without changing traversal, manifest, or writer contracts
