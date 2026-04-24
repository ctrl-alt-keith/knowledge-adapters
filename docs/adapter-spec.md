# Adapter Specification

## Purpose

This document defines the contract for source adapters in this repository.

The initial implementation target is Confluence, but the contract is intended to be generic enough to support future adapters.

## Adapter Responsibilities

An adapter must:

1. accept runtime-provided source configuration

2. resolve a target into a canonical identifier

3. fetch content and relevant metadata from the source

4. normalize the result into the repository's local artifact format

5. persist outputs to a specified local directory

6. track state in a manifest or equivalent metadata file

7. report useful success/failure outcomes

8. avoid embedding environment-specific details in the repo

## Runtime Inputs

Adapters should accept, directly or indirectly, the following classes of input:

### Required

- source base URL or equivalent locator

- authentication method or credential reference

- target page/resource identifier

- output directory

### Optional

- fetch mode (`single`, `tree`)

- recursion depth

- manifest path

- dry-run flag

- update/since filters

- timeout/retry settings

## Configuration Principles

Configuration precedence should be:

1. CLI arguments

2. local config file outside the repo

3. environment variables

4. safe defaults

Environment-specific config must remain outside the repo.

## Canonical Adapter Flow

```text

config -> resolve -> fetch -> normalize -> persist -> report
```

## Proposed Web Resource Adapter Contract

This section defines the bounded contract for a future `web_resource` adapter.
It is a design contract only; it does not imply that the adapter exists yet.

### Purpose

The `web_resource` adapter solves the narrow problem of capturing explicit,
authenticated HTTP resources that are not Confluence pages and are not local
files.

The adapter is for internal web applications that can expose useful content at
known URLs as JSON or HTML. It differs from the Confluence adapter because it
does not understand a structured vendor API, page hierarchy, or Confluence
metadata. It treats each configured URL as the unit of work and normalizes the
response into the same local artifact layout used by other adapters.

The adapter must remain generic. It should not learn application-specific route
rules, field mappings, pagination conventions, button clicks, login pages, or
domain-specific document shapes. If a source needs source-specific behavior, it
belongs in a later app-specific adapter or an explicit source-specific extension,
not in the generic `web_resource` v1 contract.

### Input Surface

Allowed v1 inputs are:

- `url`: one explicit resource URL
- `urls`: multiple explicit resource URLs supplied as repeated CLI values or a
  config list, preserving caller-provided order
- `output_dir`: local artifact output directory
- `headers_env`: optional environment variable name containing request headers
- `headers_file`: optional local file containing request headers
- `cookies_file`: optional local cookie file supplied by the caller
- `ca_bundle`: optional custom CA bundle path
- `client_cert_file`: optional client certificate path
- `client_key_file`: optional client key path
- `content_selector`: optional CSS selector for extracting a portion of an HTML
  response; XPath and advanced selector systems are out of scope for v1
- `dry_run`: optional plan-only execution flag

Secrets must not be supplied inline in committed config. Header and cookie
material should come from environment variables or local files that are outside
the repository. A future implementation may reject inline header maps in
`runs.yaml` to keep the config public-safe by default.

Path resolution should match the existing config-driven conventions:

- CLI path inputs resolve from the caller's current working directory after
  `~` expansion.
- `runs.yaml` path inputs resolve relative to the config file location after
  `~` expansion, then propagate to the adapter as resolved paths.
- `output_dir`, `headers_file`, `cookies_file`, `ca_bundle`,
  `client_cert_file`, and `client_key_file` are path inputs.
- URLs and selectors are values, not paths.
- Config-driven execution should pass only the selected run's resolved inputs to
  the adapter command, preserving the top-level `runs:` order.

### Supported Content Types

JSON is the primary v1 content type. For `application/json` and compatible
structured JSON responses, the adapter should parse the body as JSON and
normalize it into deterministic markdown or text. Object keys should be emitted
in a stable order when the response format does not already provide an ordered
representation. Nested JSON structures should be preserved, not flattened.

HTML is the secondary v1 content type. For `text/html` and compatible HTML
responses, the adapter should extract readable text or markdown from the
document. When `content_selector` is provided, extraction is limited to the
matched portion of the document. When no selector is provided, extraction uses a
generic readable-body strategy and must not apply app-specific parsing rules.

Unknown or unsupported content types should fail clearly by default before
writing an artifact. A future explicit text fallback may be added later, but v1
should not silently persist binary, image, archive, or application-specific
formats as if they were normalized knowledge artifacts.

### Output Model

The adapter writes one artifact per configured resource. Each resource produces
a normalized markdown or text artifact under the selected `output_dir` using the
existing adapter artifact layout.

The manifest records one entry per resource with these fields:

- `canonical_id`: required URL-based identifier derived from the final
  normalized URL after redirects, if redirects are followed
- `source_url`: required original configured URL
- `title`: optional title from JSON metadata, an HTML `<title>`, or another
  generic response-level title when available
- `fetched_at`: required timestamp for the fetch attempt that produced the
  artifact
- `content_hash`: optional hash of the normalized artifact content

Ordering must be deterministic. Resources are processed and reported in the
caller-provided URL order after de-duplicating by `canonical_id`. Manifest
entries and dry-run summaries should use that same order so repeated runs are
stable and easy to review.

### Authentication Model

The v1 adapter does not automate login flows. It relies only on request material
that the caller has already obtained outside the adapter:

- mTLS through `ca_bundle`, `client_cert_file`, and `client_key_file`
- request headers supplied from `headers_env` or `headers_file`
- cookies supplied from `cookies_file`

SAML, MFA, OAuth browser handoffs, and interactive login pages are outside the
adapter. Operators may use their existing internal tools to obtain a cookie or
header file, then pass that material into `web_resource`. The adapter should not
own token refresh, browser profiles, credential vault integration, or identity
provider workflows in v1.

### Execution Model

Each resource follows the same bounded flow:

```text

fetch -> normalize -> write per resource
```

The adapter performs HTTP fetches, validates content type, normalizes response
content, and writes one artifact plus manifest metadata per resource. It does
not click, scroll, submit forms, wait for client-side rendering, or otherwise
interact with a UI.

Redirect handling may be supported as an option. If redirects are followed,
`canonical_id` should be based on the final normalized URL while `source_url`
remains the original configured URL. Fetch and dry-run reporting should make the
redirect behavior visible when the two differ.

### Explicitly Out of Scope

The generic `web_resource` v1 adapter does not include:

- Playwright or browser automation
- login automation, including SAML, MFA, or OAuth browser flows
- app-specific parsing or source-specific field mapping
- pagination crawling beyond explicitly configured URLs
- link discovery, sitemap crawling, or recursive traversal
- DOM interaction such as clicking, typing, scrolling, or form submission
- LLM-specific formatting or prompt-oriented output shaping
- a caching layer, which is covered separately by issue #146
- binary asset capture, screenshots, attachments, or archive extraction

### Relationship to Existing Adapters

The `web_resource` adapter should parallel Confluence where the repository has
already proven stable patterns:

- runtime-injected config
- `output_dir`-scoped artifact writing
- manifest reporting
- dry-run planning
- TLS input names: `ca_bundle`, `client_cert_file`, and `client_key_file`
- config-driven multi-run propagation from `runs.yaml`
- clear CLI errors before writes when required inputs are invalid

It should intentionally differ from Confluence in these ways:

- no source API model beyond HTTP responses
- no page tree traversal
- no source-specific auth strategy such as `CONFLUENCE_BEARER_TOKEN`
- no Confluence metadata assumptions
- no incremental or cache behavior in v1

It should also differ from `local_files` because the source is remote HTTP
content rather than a local UTF-8 file. The useful shared behavior is the same
artifact and manifest discipline, not a shared implementation abstraction.

### Minimal v1 CLI Shape

A minimal first CLI could look like:

```bash
knowledge-adapters web_resource \
  --url https://example.internal/api/status \
  --output-dir ./artifacts/web/status \
  --ca-bundle ./certs/internal-ca.pem \
  --client-cert-file ./certs/client.crt \
  --client-key-file ./certs/client.key
```

Optional auth material can be layered on without changing the resource model:

```bash
knowledge-adapters web_resource \
  --url https://example.internal/page \
  --headers-file ./secrets/headers.txt \
  --cookies-file ./secrets/cookies.txt \
  --content-selector main \
  --output-dir ./artifacts/web/page
```

Inline `runs.yaml` example:

`runs:` `- name: internal-status` `type: web_resource`
`url: https://example.internal/api/status`
`output_dir: ./artifacts/web/internal-status`
`headers_file: ./secrets/internal-status.headers`
`ca_bundle: ./certs/internal-ca.pem`
`client_cert_file: ./certs/client.crt`
`client_key_file: ./certs/client.key`
