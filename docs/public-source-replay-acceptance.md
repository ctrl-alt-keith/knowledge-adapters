# Public Source Replay Acceptance

This note defines the local acceptance contract for known public-source replay
shapes before returning to knowledge-vault replay.

The goal is not perfect extraction. The goal is for `knowledge-adapters` to
assert that the known public-source shapes are behaving predictably enough that
knowledge-vault replay can be used as confirmation and provenance, not as the
primary discovery loop.

## Known Sources

The current acceptance contract covers:

- DORA 2023 public PDF
- MeaningfulTech webpage
- DORA ROI 2026 public PDF non-regression

Each source has a stable source key in
`knowledge_adapters.public_replay_acceptance` and a deterministic fixture in
`tests/fixtures/public_replay_acceptance/source_acceptance_metadata.json`.

## Contract Shape

Each known source asserts:

- replay classification, including `review-ready` vs `diagnostic-only`
- public webpage source-intent state, including wrapper/target-mismatch
  signals when present
- promotion state and promotion blockers
- reviewability assessment, including bounded review economics
- deterministic cleanup counts or ranges
- remaining artifact counts or ranges
- known limitation codes
- intentional-retention markers

The numeric checks intentionally use bounded ranges, not exact hashes. They
should fail when expected cleanup disappears, remaining artifacts regress
sharply, or a source shape changes enough that review economics are no longer
trusted.

## Report Surface

Use the live milestone check intentionally:

```bash
knowledge-adapters public_replay_acceptance
```

To check one source:

```bash
knowledge-adapters public_replay_acceptance --source dora_2023_public_pdf
knowledge-adapters public_replay_acceptance --source meaningfultech_webpage
knowledge-adapters public_replay_acceptance --source dora_roi_2026_public_pdf
```

The command prints one `stable` or `unexpected` section per source with the
observed acceptance metrics and expected ranges. It returns nonzero when any
known source violates the local contract.

This command fetches live public sources and is not part of `make check`.
Canonical local validation remains deterministic and fixture-backed.

For public webpages, the acceptance check continues to assert the known
MeaningfulTech substantive article shape. Wrapper-page and target-discovery
coverage lives in the deterministic public webpage fixtures so the known-source
acceptance contract does not depend on a gated marketing page or on a specific
download asset remaining live.

## Non-Goals

This acceptance contract does not implement retention policy, auto-promotion,
summarization, or broader cleanup heuristics. Public-source candidates remain
unreviewed and `unsafe-to-promote` until a human retention/source review
decision is made outside this adapter.
