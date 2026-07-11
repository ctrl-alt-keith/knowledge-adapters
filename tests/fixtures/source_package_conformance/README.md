# Source package conformance vectors

`vectors.json` is a contract-derived, implementation-neutral matrix. Each
mutation starts from the same deterministic package assembled by
`tests/source_package_fixtures.py`. The `expected` and `stage` values are the
consumer outcome and earliest verification boundary required by
`docs/source-package-contract.md`.

The two resource-limit vectors use fixture-local consumer limits because the
contract deliberately assigns manifest size limits to consumers and does not
specify a universal byte or nesting limit. They test bounded rejection, not a
normative limit value.

These vectors do not import producer or consumer implementation code. When the
source-package API lands, its tests should consume the materialized package
directories and compare results with this matrix.

Contract 1.1 collection-progress vectors declare the required
`collection-progress` capability explicitly. Their verifier calls opt into the
same capability; missing-capability and pre-1.1 vectors prove that unsafe
fallback is rejected at compatibility validation.
