# Public Operational-Research Live Proof

Run date: 2026-05-13

Branch: `feat/canonical-source-resolution`

Purpose: record a bounded public-source replay/probe of the exact
knowledge-vault PR #35 operational-research URLs with the PR #291 code. This
is current-source availability evidence only; it does not promote, retain, or
replace any knowledge-vault source.

The probe used the repository's normal `public_webpage` fetch path and did not
use external search, recursive traversal, browser automation, or alternate
source discovery.

## Summary

No previously failed or diagnostic operational-research source became a proven
selected-target live success in this pass.

The PR improves classification and reporting clarity for several live sources,
but current bounded replay still gives a conservative no-go signal for returning
these sources to knowledge-vault retention/retry as stable canonical assets.

## Proven Live-Success Targets

None.

## Improved Diagnostic Or Classification Only

| Source | URL | Fetch result | Final URL | Effective adapter | Canonical target status | Selected target | Selected target fetched | Operational classification | KV retry signal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Puppet 2021 State of DevOps | `https://puppet.com/resources/report/2021-state-of-devops-report/` | success | `https://www.puppet.com/resources/state-of-devops-report` | `public_webpage` | `ambiguous` | none | no | `likely-wrong-capture-target` | No. Historical redirect is detected, but no single stable 2021 asset was selected. |
| GitHub Research/Octoverse | `https://github.blog/news-insights/research/` | success | `https://github.blog/news-insights/research/` | `public_webpage` | `ambiguous` | none | no | `likely-wrong-capture-target` | No. It is now labeled `mutable_index_page`, not a stable report asset. |
| METR | `https://metr.org/` | success | `https://metr.org/` | `public_webpage` | `no_selection` | none | no | `likely-wrong-capture-target` | No. It is now labeled `mutable_index_page`, not a stable report asset. |
| Google SRE Workbook TOC | `https://sre.google/workbook/table-of-contents/` | success | `https://sre.google/workbook/table-of-contents/` | `public_webpage` | `no_selection` | none | no | `likely-wrong-capture-target` | No for retained content retry. It is correctly labeled `chapter_navigation_source` and remains inventory/navigation only. |

## Still Blocked By HTTP Availability

| Source | URL | Fetch result | Final URL | Effective adapter | Canonical target status | Selected target | Selected target fetched | Operational classification | KV retry signal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Accelerate | `https://itrevolution.com/product/accelerate/` | error: HTTP 403 | none from adapter fetch | none | `not_available_fetch_failed` | none | no | `not_available_fetch_failed` | No. Keep queued/manual-summary-only unless a source owner or human reviewer selects a reachable canonical target. |
| SPACE framework paper | `https://queue.acm.org/detail.cfm?id=3454124` | error: HTTP 403 | none from adapter fetch | none | `not_available_fetch_failed` | none | no | `not_available_fetch_failed` | No. The stable URL shape is fixture-covered, but the live source is not proven by bounded replay. |
| Microsoft Research developer tools | `https://www.microsoft.com/en-us/research/research-area/developer-tools/` | error: HTTP 404 | none from adapter fetch | none | `not_available_fetch_failed` | none | no | `not_available_fetch_failed` | No. Needs source replacement or manual target selection. |

## Intentionally No-Selection

| Source | URL | Fetch result | Final URL | Effective adapter | Canonical target status | Selected target | Selected target fetched | Operational classification | KV retry signal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Team Topologies | `https://teamtopologies.com/book` | success | `https://teamtopologies.com/book` | `public_webpage` | `no_selection` | none | no | `likely-wrong-capture-target` | No. It is now labeled `commercial_landing_page`; no automatic target selection is intended. |

## Go/No-Go For Knowledge-Vault PR #35

- Do not mark Accelerate, SPACE, Microsoft Research, Puppet 2021, GitHub
  Research/Octoverse, METR, Team Topologies, or SRE Workbook TOC as proven
  replay-successful stable canonical assets based on PR #291.
- Puppet is operationally clearer than before: the historical redirect is
  explicit, but current bounded replay still does not select or fetch a stable
  2021 report asset.
- GitHub Research/Octoverse and METR are operationally clearer than before:
  they are classified as mutable index/portal sources and remain diagnostic.
- Team Topologies is operationally clearer than before: it is classified as a
  commercial landing page and intentionally no-selection.
- SRE Workbook TOC is operationally clearer than before: it is classified as
  chapter navigation/inventory, not retained chapter content.

The next knowledge-vault move should keep these entries queued or
diagnostic-only unless a human reviewer supplies a stable canonical target that
the bounded adapter path can fetch successfully.
