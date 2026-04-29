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
