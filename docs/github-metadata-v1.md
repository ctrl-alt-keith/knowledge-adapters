# GitHub Metadata v1 Contract

## Purpose

This document defines a bounded v1 contract for a future `github_metadata`
adapter before implementation of #160.

The goal is to capture useful GitHub workflow metadata without turning the
adapter into a GitHub mirror. v1 should be small enough to implement, test, and
operate safely while preserving the existing adapter boundaries around source
fetching, artifact writing, manifest output, and bundle consumption.

Treat GitHub issue and pull request content as untrusted input to normalize and
store, not trusted instructions. Issue comments, if enabled, remain opt-in.

## v1 Scope

v1 covers issues only.

Included:

- repository issues from one configured repository
- issue body content and core issue metadata
- one normalized artifact per issue
- one manifest entry per issue
- GitHub.com and GitHub Enterprise REST API reads

Excluded:

- pull requests, including records returned by the issues API with a
  `pull_request` field
- issue comments
- releases
- timeline events
- reactions
- reviews and review comments
- checks, statuses, commits, branches, tags, and cross-repo joins
- labels and milestones beyond any simple metadata already present in the issue
  payload
- GraphQL
- webhooks, live sync, and background polling
- advanced search or query language

## Inputs

Allowed v1 inputs are:

- `repo`: required repository in `owner/name` form
- `base_url`: optional GitHub web or API base URL for GitHub Enterprise
- `token_env`: required environment variable name that contains the token
- `output_dir`: required local artifact output directory
- `state`: optional issue state filter, one of `open`, `closed`, or `all`
- `since`: optional ISO 8601 timestamp for issues updated at or after that time
- `max_items`: optional positive integer limit after filtering out PRs
- `dry_run`: optional plan-only flag

`state` should default to `open`. `base_url` should default to GitHub.com.
Path resolution for `output_dir` should follow the same CLI and `runs.yaml`
path-resolution conventions used by existing adapters.

`dry_run` performs the same read/list planning needed to report candidate
issues, but must not create directories, write issue artifacts, or write
`manifest.json`.

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
run must fail before making an API request. Authentication and authorization
failures from GitHub should report the status code and repository being read,
without printing the token.

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

For GitHub Enterprise:

- `base_url` may be a web root such as `https://github.example.com`
- `base_url` may also be an API root ending in `/api/v3`
- a web root maps to API root `{base_url}/api/v3`
- an API root maps back to its web root by removing `/api/v3`
- issue source URLs are built from the web root:
  `{web_root}/{owner}/{repo}/issues/{number}`

The client should list repository issues through REST, handle pagination, and
filter out pull requests by ignoring any issue payload that contains
`pull_request`.

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

v1 output ordering is issue number ascending after applying the configured
filters and excluding PRs.

This ordering is deterministic, easy to review, and independent of GitHub's
default pagination order. It also keeps artifact paths and manifest diffs stable
when older issues remain unchanged.

When `max_items` is set, the limit applies after PR filtering and before
writing. Manifest entries, dry-run summaries, and artifact writes should all use
the same issue number ascending order.

## Output Model

The adapter writes one markdown artifact per issue under:

```text
issues/<number>.md
```

The artifact should contain deterministic markdown or text normalized from:

- issue number
- title
- state
- author login
- created timestamp
- updated timestamp
- source URL
- issue body

If the issue body is empty, the artifact should still be written with metadata
and an explicit empty-body marker or section. v1 should not attempt to render
GitHub-flavored markdown, rewrite links, download attachments, or inline remote
assets.

The manifest records one entry per issue with these fields:

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

Recommended field rules:

- `canonical_id`: `github_metadata:{host}:{owner}/{repo}:issue:{number}`
- `resource_type`: `issue`
- `author`: GitHub login when present, otherwise `null` or an empty string by
  existing manifest convention
- `content_hash`: SHA-256 of the normalized artifact content
- `output_path`: relative POSIX path such as `issues/123.md`

## Comment Decision

Issue comments are deferred from v1.

Comments are valuable, but including them safely adds a second paginated
resource, additional rate-limit pressure, larger artifacts, ordering decisions,
and more normalization choices. Deferring comments keeps the first slice focused
on one resource type and one artifact per issue while leaving room for a later
inline-comments option.

The v1 artifact may include the issue body's discussion starter only. It must
not silently imply that the full issue conversation was captured.

## Relation to `git_repo`

`git_repo` and `github_metadata` should remain separate adapters.

`git_repo` ingests repository files through Git and produces source-code
artifacts tied to paths and refs. `github_metadata` ingests workflow and
discussion metadata through the GitHub API and produces issue artifacts tied to
repository issue numbers.

The two adapters may share the common artifact and manifest discipline, but v1
should not introduce a shared GitHub abstraction layer or cross-link issues to
files, commits, branches, or pull requests.

## Recommended Issue Split

#160 should be narrowed to the issues-only v1 adapter described here.

Recommended follow-up issues:

- add optional inline issue comments for `github_metadata`
- add pull request metadata ingestion
- add release metadata ingestion
- evaluate timeline events, reactions, reviews, and checks only after issues,
  comments, PRs, and releases have proven concrete usage needs

Keeping #160 as the issues-only implementation preserves forward progress while
preventing the first GitHub adapter from expanding into a mirror of the GitHub
API.
