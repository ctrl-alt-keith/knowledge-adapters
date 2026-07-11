# Source Package Conformance Matrix

This matrix is derived only from the normative contract in
[`source-package-contract.md`](source-package-contract.md). The machine-readable
source is `tests/fixtures/source_package_conformance/vectors.json`.

| Expected result | Cases |
| --- | --- |
| Accept | minimal valid `completed`; valid `completed_with_errors`; optional sealed run receipt |
| Reject before manifest trust | malformed sidecar; uppercase digest; missing newline; digest mismatch; manifest changed without sidecar update |
| Reject during manifest/compatibility validation | malformed UTF-8; malformed JSON; duplicate object key; unsupported major; unknown required capability |
| Reject during inventory/integrity validation | artifact digest mismatch; size mismatch; missing inventoried artifact; undeclared handoff artifact |
| Reject during path validation | duplicate path identity; absolute path; `..` escape |
| Reject during terminal/item validation | inconsistent counts; nonterminal item in sealed package; completed item carrying an error |
| Reject during lineage validation | optional receipt contradicts authoritative manifest lineage |
| Reject at consumer-defined resource limits | manifest over 4096 fixture bytes; JSON deeper than 16 fixture levels |

The resource-limit values are test parameters, not contract constants. The
contract requires consumers to check their own manifest size limits before
hashing, but leaves the numeric limits unspecified. It also does not prescribe
a JSON nesting limit; the fixture records an explicit defensive consumer limit
without claiming it is normative.

## Public verifier integration

Every vector is materialized and passed only to the public `verify_package`
boundary from PR #316. Tests assert the result state, earliest stable rejection
stage, and specified stable finding code. The fixture materializer remains
contract-derived and does not import implementation helpers.
