# Public PDF DORA Regression Fixtures

This note defines the CAK-15 extraction-quality iteration workflow for DORA-like
public PDF replay noise.

## Primary Feedback Loop

Use deterministic, sanitized fixtures in
`tests/fixtures/public_pdf/dora_regression_cases.json` as the primary
extraction-quality iteration loop for public PDF normalization changes.

The fixture area captures small DORA-derived extraction shapes for:

- repeated footer blocks
- leading-space numeric page lines
- ordinary page-number/footer pairs
- repeated multi-line trailing footer blocks
- large-document high-coverage repeated trailing title/version footer blocks
- URL scheme-spacing artifacts
- URL path line-wrap artifacts
- one-letter split-word line wraps
- mid-page footer-like text
- calculator and table numeric traps
- fused extraction artifacts such as `roadmap43`

Each case states whether current behavior should normalize the artifact or
leave it unchanged for safety. Tests in
`tests/test_public_pdf_dora_regression_fixtures.py` validate the normalized
pages, no-op safety cases, replay-quality metadata, and previously observed
DORA replay failures.

When a DORA replay exposes a new extraction-quality problem, reduce it to the
smallest sanitized fixture first. Iterate in `knowledge-adapters` until the
fixture and `make check` pass, then use larger replays for integration
confidence.

## Knowledge-Vault Replay Role

Knowledge-vault replay is milestone and integration validation, not the main
inner loop for public PDF extraction-quality tuning.

Use full replay validation when the change needs evidence that cannot be proven
inside fixture tests, including:

- candidate artifact shape across the real destination tree
- manifest and content-hash behavior over a full run
- interaction with existing knowledge-vault review workflows
- source-specific replay diffs before requesting review or merge of a risky
  extraction-quality change
- confirmation that a sanitized fixture faithfully represents a newly observed
  live replay failure

Do not use repeated full replays as the normal way to discover whether a small
normalization rule works. Keep the fast fixture loop authoritative for unit
behavior, and treat replay output as end-to-end validation evidence.

## Metadata Expectations

Replay-quality metadata is part of the fixture contract. It remains
informational only and does not authorize retention or promotion. Fixture tests
should assert counts and notes that help reviewers understand what mechanical
conditions were observed, such as URL repairs, footer suppression, numeric-risk
diagnostics, page-count context, and extraction warnings.

## Limitations And Non-Goals

The fixture workflow does not change retention semantics, add auto-promotion
logic, broaden ingestion behavior, infer report structure, or repair ambiguous
body text by default.

Known limitations should be fixture-backed when useful. For example,
`fused_extraction_artifact_roadmap43` documents that fused body-text/page-number
artifacts are currently retained unchanged and must be reviewed against the
source PDF before retention.
