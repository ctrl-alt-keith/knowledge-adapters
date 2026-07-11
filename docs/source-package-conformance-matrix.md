# Source Package Conformance Matrix

This matrix is derived only from the normative contract in
[`source-package-contract.md`](source-package-contract.md). The machine-readable
source is `tests/fixtures/source_package_conformance/vectors.json`.

| Expected result | Cases |
| --- | --- |
| Accept | minimal valid `completed`; valid `completed_with_errors`; optional sealed run receipt; exhausted collection; continuation remaining; resumed collection |
| Reject before manifest trust | malformed sidecar; uppercase digest; missing newline; digest mismatch; manifest changed without sidecar update |
| Reject during manifest/compatibility validation | malformed UTF-8; malformed JSON; duplicate object key; unsupported major; unknown required capability |
| Reject collection-progress compatibility | missing required `collection-progress` capability; progress on a pre-1.1 contract |
| Reject during inventory/integrity validation | artifact digest mismatch; size mismatch; missing inventoried artifact; undeclared handoff artifact |
| Reject during path validation | duplicate path identity; absolute path; `..` escape |
| Reject during terminal/item validation | inconsistent counts; nonterminal item in sealed package; completed item carrying an error |
| Reject during lineage validation | optional receipt contradicts authoritative manifest lineage |
| Reject collection-progress semantics | unknown state; extra fields; malformed resume lineage |
| Reject at consumer-defined resource limits | manifest over 4096 fixture bytes; JSON deeper than 16 fixture levels |
| Reject compound failures by earliest stage | terminal accounting before artifact integrity; item semantics before artifact integrity; lineage before artifact integrity |

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

Public-result safety tests also confirm schema version `2.3.0`, curated claims,
exclusion of arbitrary extensions and fields, absence of raw-manifest access,
and stage-bounded claims on rejection.

Deterministic public-API I/O seams additionally cover item and optional receipt
read failures, changed item and receipt bytes between semantic and final
integrity stages, and an inventoried file disappearing before its final read.
All failures return structured results; the mutation cases prove final
integrity does not trust semantic-stage byte caches. These tests supplement the
unchanged 29-vector matrix.
