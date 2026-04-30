# Adapter Readiness Report

The adapter readiness report is a lightweight coverage map for reliability
work. It is not a quality score, release gate, dashboard, badge, or persistent
tracking system.

Run it locally with:

```bash
make adapter-readiness
```

The report is deterministic plain text. It starts from the explicit model in
`src/knowledge_adapters/adapter_readiness.py` rather than scraping test names or
inferring coverage from the filesystem.

## Dimensions

- Contract/invariant: the adapter has focused coverage registered against the
  shared adapter contract or invariant helpers for successful normalized
  artifacts and manifests.
- Chaos: the adapter has deterministic local chaos tests registered for named
  failure scenarios.
- Replay: the adapter's chaos coverage can be rerun through the repository
  replay target, such as `make chaos-replay`.
- No partial artifacts: the adapter has failure-path coverage showing known
  deterministic failures do not leave partial markdown artifacts or
  `manifest.json` behind.

## Updating Coverage

When an adapter gains one of these reliability dimensions, update the explicit
readiness model with the observed coverage and a short evidence note pointing
to the test, helper, or Makefile target that proves it. Keep entries factual:
describe coverage that exists in the repository today, not planned or desired
coverage.

Future adapters should be added to the model when they become real adapter CLI
surfaces. They can start with `no` for dimensions they do not yet cover. Do not
force a new adapter to add chaos or contract coverage just to appear in the
report.

If a future dimension would require fragile test-name parsing, keep it out of
the report until it can be represented explicitly.
