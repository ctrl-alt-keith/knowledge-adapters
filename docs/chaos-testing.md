# Chaos Testing Utilities

The repository includes deterministic, test/dev-only chaos helpers in
`tests/chaos.py`. They let adapter tests exercise realistic failure behavior
without credentials, live services, sleeps, or external network calls.

Available Confluence HTTP scenarios:

- `timeout`
- `rate_limit`
- `invalid_json`
- `empty_response`
- `partial_payload`

Use the shared `confluence_chaos` fixture in tests that need to harden real
client or CLI failure handling:

```python
from tests.chaos import AdapterChaosScenario


def test_adapter_failure(confluence_chaos):
    confluence_chaos(AdapterChaosScenario.TIMEOUT)

    # Run the adapter path under test. urllib.request.urlopen is patched and
    # CONFLUENCE_BEARER_TOKEN is set to a deterministic test value.
```

Keep chaos scenarios deterministic and local to tests. Do not add production
chaos injection or scenarios that require live services, real credentials, or
timing-sensitive assertions.

## Running Chaos Validation

Use `make chaos-random` for a cheap canary. It selects one scenario from the
current chaos suite, prints the seed, prints the selected scenario, and then
runs only the chaos tests for that scenario. Supplying the same seed selects the
same scenario:

```bash
make chaos-random CHAOS_SEED=issue-247
```

When `chaos-random` runs, it also prints a rerun command that pins both values:

```bash
CHAOS_REPLAY_COMMAND: make chaos-replay CHAOS_SEED=<printed-seed> CHAOS_SCENARIO=<printed-scenario>
```

In GitHub Actions, `chaos-random` uses `ci-$GITHUB_SHA` when no explicit
`CHAOS_SEED` is supplied. Local developer runs keep their existing timestamp
fallback unless you pass `CHAOS_SEED` yourself. Use the printed command to
reproduce a CI or local canary failure exactly.

Use `make chaos-all` when you want the complete current chaos suite. That is the
right target for local hardening before changing adapter failure behavior, and
for scheduled automation that can spend more time on exhaustive chaos coverage.

## Replaying Failures

Use `make chaos-replay` to rerun a pinned chaos scenario without relying on
local run history:

```bash
make chaos-replay CHAOS_SCENARIO=timeout
```

When a chaos test fails, pytest prints a node-specific replay command in the
terminal summary:

```bash
CHAOS_FAILURE_REPLAY_COMMAND: make chaos-replay CHAOS_SEED=<seed> CHAOS_SCENARIO=<scenario> CHAOS_NODEID='<pytest-node-id>'
```

`CHAOS_SEED` is included when the failing run had one, such as a
`make chaos-random` canary. `CHAOS_SCENARIO` is required so replay commands stay
explicit. `CHAOS_NODEID` is optional; omit it to rerun every chaos test matching
the pinned scenario.

## Failure Fingerprints

Chaos failures also print a `CHAOS_FAILURE_FINGERPRINT: chaos-v1:<digest>`
line with a compact JSON payload. The digest and payload are deterministic for
the same failure context:

- `scenario`
- `nodeid`
- `failure_type`
- `failure_message`
- `command_context`

Use the fingerprint to recognize repeated failures across local runs and CI
logs. Use the replay command next to the fingerprint to reproduce the specific
scenario and pytest node. Fingerprints are intentionally lightweight log output;
they are not persisted by the repository and do not imply any run history,
database, dashboard, or production chaos behavior.

The pull request CI workflow runs `make chaos-random` as a quick signal while
leaving `make check` as the repository's canonical validation path.

The adapter readiness report in [`adapter-readiness.md`](adapter-readiness.md)
summarizes which current adapters have chaos and replay coverage registered.
Update that explicit model when new adapter chaos scenarios are added.
