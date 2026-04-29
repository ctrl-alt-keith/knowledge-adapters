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
make chaos-random CHAOS_SEED=<printed-seed> CHAOS_SCENARIO=<printed-scenario>
```

Use that command to reproduce a random CI or local canary failure exactly.

Use `make chaos-all` when you want the complete current chaos suite. That is the
right target for local hardening before changing adapter failure behavior, and
for scheduled automation that can spend more time on exhaustive chaos coverage.

The pull request CI workflow runs `make chaos-random` as a quick signal while
leaving `make check` as the repository's canonical validation path.
