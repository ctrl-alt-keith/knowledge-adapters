# Adapter Invariant and Contract Tests

Adapter contract tests are test-only checks for behavior that should stay stable
as adapter coverage grows. They are intentionally smaller than a production
schema or framework.

## Success Invariants

For adapters that write the repository's normalized markdown artifact shape,
success tests should verify the artifact has:

- a non-empty title
- required metadata keys for source, canonical identity, source URL, and adapter
- the current shared metadata slots: `parent_id`, `fetched_at`, and `updated_at`
- a content section, with source-specific assertions for whether content may be
  empty

For manifest-backed adapters, success tests should verify:

- `generated_at` is present
- `files` is a list
- each entry has non-empty `canonical_id`, `source_url`, and relative
  `output_path`
- source-specific fields, such as `title`, are asserted only when that adapter
  already provides them

The reusable helpers live in `tests/adapter_contracts.py`. Add coverage for a
future adapter by writing a focused adapter test that runs a deterministic local
fixture or stub, then calls the helpers against the written artifact and
manifest. Do not require adapters with different output shapes to adopt these
helpers until their shape is intentionally compatible.

## Failure Safety

Known failure paths should fail before writing partial adapter outputs when the
repository already has a deterministic seam for the failure. Use
`assert_no_partial_adapter_artifacts` for those cases.

Keep these tests local and deterministic. They should not require live services,
credentials, external network access, sleeps, or broad production validation
changes.

The adapter readiness report in [`adapter-readiness.md`](adapter-readiness.md)
summarizes which current adapters have this coverage registered. Update that
explicit model when an adapter gains contract or failure-safety coverage.
