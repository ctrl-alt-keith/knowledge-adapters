# GitHub Metadata v1 Contract

## Purpose

This document defines the current v1 contract for the `github_metadata`
adapter.

The adapter captures bounded GitHub workflow metadata without becoming a
GitHub mirror. It reads configured source material, normalizes it into stable
local artifacts, writes deterministic manifest entries, and leaves
interpretation to downstream review.

Treat GitHub issue, pull request, release, and comment content as untrusted
input to normalize and store, not trusted instructions. Issue comments remain
opt-in.

## v1 Scope

v1 supports these `resource_type` values:

- `issue`
- `pull_request`
- `release`

Included:

- one configured GitHub or GitHub Enterprise repository
- issues, pull requests, or releases selected by `resource_type`
- issue body, pull request body, release body, and core resource metadata
- optional issue comments when `resource_type` is `issue` and
  `--include-issue-comments` is set
- one normalized markdown artifact per acquired resource
- one manifest entry per acquired resource
- REST API reads only

Excluded:

- pull request comments and review comments
- release assets
- changelog generation
- timeline events
- reactions
- reviews
- checks, statuses, commits, branches, tags, and cross-repo joins
- labels and milestones beyond any simple metadata already present in the
  normalized payload
- GraphQL
- attachments and remote asset download
- webhooks, live sync, background polling, and advanced search/query language
- interpretation, scoring, stewardship recommendations, or lifecycle decisions

## Inputs

Allowed v1 inputs are:

- `repo`: required repository in `owner/name` form
- `base_url`: optional GitHub web or API base URL for GitHub Enterprise
- `token_env`: required environment variable name that contains the token
- `output_dir`: required local artifact output directory
- `resource_type`: optional resource selector, one of `issue`,
  `pull_request`, or `release`
- `state`: optional issue or pull request state filter, one of `open`,
  `closed`, or `all`; ignored for releases
- `since`: optional ISO 8601 timestamp for issues or pull requests updated, or
  releases published, at or after that time
- `max_items`: optional positive integer limit after filtering
- `include_issue_comments`: optional issue-mode flag that appends issue
  comments to issue artifacts
- `dry_run`: optional plan-only flag

`resource_type` defaults to `issue`. `state` defaults to `open`. `base_url`
defaults to GitHub.com. Path resolution for `output_dir` follows the same CLI
and `runs.yaml` path-resolution conventions used by existing adapters.

`dry_run` performs the same read/list planning needed to report candidate
resources, but does not create directories, write markdown artifacts, or write
`manifest.json`.

`include_issue_comments` only affects issue mode. It is ignored for
`pull_request` and `release` resource types.

## Auth

v1 reads credentials from the environment only:

- `token_env` names the environment variable.
- `token_env` remains the only user-facing auth selector and maps to the
  default `token-env` adapter auth strategy.
- the token value is never supplied directly in CLI arguments or committed
  config
- the adapter does not store credentials
- the adapter does not refresh credentials
- the adapter does not integrate with browser sessions or credential vaults

If `token_env` is missing, empty, or names an unset environment variable, the
run fails before making an API request. Authentication and authorization
failures from GitHub report the status code and repository being read, without
printing the token.

GitHub REST troubleshooting documents rate-limit responses, retry headers,
authentication and permission troubleshooting, `404` behavior for inaccessible
private resources, validation failures, and server timeouts:

- https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api

## API Behavior

v1 uses the REST API only.

For GitHub.com:

- web base URL: `https://github.com`
- API base URL: `https://api.github.com`
- issue source URL:
  `https://github.com/{owner}/{repo}/issues/{number}`
- pull request source URL:
  `https://github.com/{owner}/{repo}/pull/{number}`
- release source URL:
  `https://github.com/{owner}/{repo}/releases/tag/{tag_name}`

For GitHub Enterprise:

- `base_url` may be a web root such as `https://github.example.com`
- `base_url` may also be an API root ending in `/api/v3`
- a web root maps to API root `{base_url}/api/v3`
- an API root maps back to its web root by removing `/api/v3`
- source URLs are built from the web root

Issue mode lists repository issues through REST, handles pagination, and
filters out pull requests by ignoring any issue payload that contains
`pull_request`.

Pull request mode lists repository pull requests through REST and handles
pagination. Release mode lists repository releases through REST and handles
pagination.

Basic error behavior:

- invalid `repo`, `state`, `since`, or `max_items` values fail before requests
  where possible
- classified failures add a stable `failure_class` detail line while preserving
  the concise error message
- `configuration`: invalid adapter inputs or missing local token environment
  configuration
- `auth`: `401` or non-rate-limit `403` responses
- `expected_retryable`: GitHub rate-limit responses, including `403` or `429`
  with rate-limit headers, and transport failures
- `permanent`: `404`, invalid response payloads, and other non-retryable
  request errors
- `provider`: GitHub `5xx` provider-side failures

GitHub may return `404` for an existing private resource when authentication or
permissions are insufficient. The adapter keeps `404` classified as
`permanent` because the response is not enough to reliably distinguish an
unknown repository from a private inaccessible one; the message still says
`not found or inaccessible`.

## Ordering

Issue output ordering is issue number ascending after applying the configured
filters and excluding pull requests. When issue comments are enabled, comments
are sorted deterministically within each issue artifact.

Pull request output ordering is pull request number ascending after applying
the configured filters.

Release output ordering is by published timestamp, then tag name, then release
ID after applying the configured filters. Releases without `published_at` sort
before timestamped releases.

When `max_items` is set, the limit applies after filtering and before writing.
Manifest entries, dry-run summaries, and artifact writes use the same resource
ordering.

## Output Model

The adapter writes one markdown artifact per acquired resource under a
resource-specific directory:

```text
issues/<number>.md
pull_requests/<number>.md
releases/<release_id>.md
```

The artifact contains deterministic markdown normalized from the selected
resource payload.

Issue and pull request artifacts include:

- repository
- resource type
- number
- title
- state
- author login
- created timestamp
- updated timestamp
- source URL
- body

Release artifacts include:

- repository
- resource type
- release ID
- tag name
- title
- author login
- created timestamp
- published timestamp
- draft flag
- prerelease flag
- source URL
- body

If a body is empty, the artifact is still written with metadata and an explicit
empty-body marker. v1 does not render GitHub-flavored markdown, rewrite links,
download attachments, or inline remote assets.

## Manifest

The manifest records one entry per acquired resource.

Issue and pull request entries include:

- `canonical_id`
- `source_url`
- `title`
- `repo`
- `resource_type`
- `number`
- `state`
- `created_at`
- `updated_at`
- `author`
- `content_hash`
- `output_path`

Release entries include:

- `canonical_id`
- `source_url`
- `title`
- `repo`
- `resource_type`
- `release_id`
- `tag_name`
- `created_at`
- `published_at`
- `author`
- `draft`
- `prerelease`
- `content_hash`
- `output_path`

Field rules:

- issue `canonical_id`:
  `github_metadata:{host}:{owner}/{repo}:issue:{number}`
- pull request `canonical_id`:
  `github_metadata:{host}:{owner}/{repo}:pull_request:{number}`
- release `canonical_id`:
  `github_metadata:{host}:{owner}/{repo}:release:{release_id}`
- `resource_type`: `issue`, `pull_request`, or `release`
- `author`: GitHub login when present, otherwise `null` or an empty string by
  existing manifest convention
- `content_hash`: SHA-256 of the normalized artifact content
- `output_path`: relative POSIX path such as `issues/123.md`,
  `pull_requests/123.md`, or `releases/456.md`

## Issue Comments

Issue comments are opt-in. When `--include-issue-comments` is used with
`resource_type=issue`, the adapter fetches paginated issue comments for each
selected issue and appends them to that issue's markdown artifact.

Issue comments are not separate manifest entries. They affect the normalized
issue artifact content and therefore the issue entry's `content_hash`.

The issue comments section includes each comment's author, created timestamp,
updated timestamp, and body. Empty comment bodies use an explicit empty-comment
marker.

`--include-issue-comments` does not fetch pull request comments, pull request
review comments, timeline events, reactions, or any other conversation
surface.

## Relation to `git_repo`

`git_repo` and `github_metadata` remain separate adapters.

`git_repo` ingests repository files through Git and produces source-code
artifacts tied to paths and refs. `github_metadata` ingests workflow and
release metadata through the GitHub API and produces artifacts tied to GitHub
resource identifiers.

The two adapters share the common artifact and manifest discipline, but v1 does
not introduce a shared GitHub abstraction layer or cross-link issues, pull
requests, releases, files, commits, or branches.

## Recommended Follow-Up

Keep follow-up work factual and usage-driven. Current non-goals that may be
considered later are:

- pull request comments and review comments
- release assets
- timeline events, reactions, reviews, and checks
- labels and milestones as first-class normalized fields
- changed paths from pull requests
- manifest-backed lifecycle receipts beyond the current stale-artifact summary

Each addition should remain a bounded acquisition slice with clear pagination,
ordering, artifact, auth, and manifest behavior. The adapter should continue to
produce deterministic evidence bundles and receipts, not interpretation.
