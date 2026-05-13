# CAK-15 Public PDF Footer Divergence Audit

Date: 2026-05-13

Scope: focused execution-path audit for the DORA ROI public PDF footer
suppression divergence after PR #285.

## Root Cause

The DORA-derived fixture tests and the real public PDF replay use the same
normalization function:
`knowledge_adapters.public_pdf.normalize.normalize_extracted_pages_with_replay_metadata`.

The divergence was inside anchored footer suppression, not in the replay entry
point or metadata/body split. The real DORA ROI extraction has a repeated
`v. 2026.1` footer anchor on 57 pages, but not every anchor occurrence has a
safe adjacent bare numeric page line:

- page 43 has the fused body/footer artifact `roadmap43` before `v. 2026.1`
- page 59 has an adjacent numeric line near reference-list numeric content

Before this fix, either condition cancelled the entire repeated anchor group.
That made diagnostics report repeated trailing footer signatures while anchored
suppression reported zero detected blocks and the candidate body stayed
unchanged.

## Execution Path Evidence

Stage ordering for `public_pdf` is:

1. `fetch_pdf()` fetches the PDF and extracts page text with `pypdf`.
2. `normalize_extracted_pages_with_replay_metadata()` repairs URL spacing and
   URL path line wraps.
3. Footer diagnostics run on post-URL-normalized page text before suppression.
4. Anchored footer suppression runs on that same normalized page list.
5. `fetch_pdf()` renders one `## Page N` block per suppressed page.
6. CLI `public_pdf` passes that candidate content to `normalize_to_markdown()`.
7. The CLI hashes the same rendered markdown used for the candidate body and
   stores replay-quality metadata in the manifest entry.
8. `run` invokes the configured adapter by calling the same in-process
   `main(argv)` entry point and captures its summary for the run report.

The fixture suite directly exercises the page normalizer, so it covers the
same normalization and suppression function as real replay. It does not cover
`pypdf` extraction, fetching, config-driven `run`, or installed-entry-point
selection.

## Installed Path Evidence

The replay note said it used
`/Users/keith/src/ctrl-alt-keith/knowledge-adapters/.venv/bin/knowledge-adapters`
at commit `4ceebb6`. Local inspection of that environment showed:

- distribution version: `knowledge-adapters` 0.8.0
- package path:
  `/Users/keith/src/ctrl-alt-keith/knowledge-adapters/src/knowledge_adapters`
- normalize path:
  `/Users/keith/src/ctrl-alt-keith/knowledge-adapters/src/knowledge_adapters/public_pdf/normalize.py`
- entry point imports `knowledge_adapters.cli:main`
- checkout HEAD: `4ceebb6cfa0a0955425b72c76655250958bcc0fb`

Version `0.8.0` alone is not sufficient proof of the code path because several
CAK-15 changes shared that version. The replay note's commit and entry-point
path were enough to rule out a stale installed package for this audit.

## Live Source Evidence

Before the fix, a live DORA ROI inspection on current main produced:

- page count: 60
- repeated trailing footer block count: 2
- bare numeric trailing line count: 57
- suppression activity: none
- suppressed line count: 0
- detected anchored footer block count: 0
- `v. 2026.1` lines in content: 58
- numeric lines immediately before `v. 2026.1`: 57

Shape inspection found:

- `(numeric_depth=2, anchor_depth=1)` on 56 pages
- `(numeric_depth=20, anchor_depth=19)` on page 6
- one missing adjacent numeric line in the trailing anchor group on page 43:
  `Map your AI investment roadmap43` followed by `v. 2026.1`
- one numeric-risk page in the trailing anchor group on page 59, where the
  candidate page number follows reference-list numeric content

After the fix, the same live source through the worktree editable install
reported:

- suppression activity: suppressed
- suppressed line count: 110
- affected page count: 55
- detected anchored footer block count: 1
- suppressed anchored footer block count: 1
- suppressed numeric page-line count: 55
- skipped numeric risk count: 1
- `v. 2026.1` lines in content: 3
- numeric lines immediately before `v. 2026.1`: 2
- `roadmap43` followed by `v. 2026.1` retained

## Fix Summary

Anchored suppression now classifies pages within a repeated anchor group
individually:

- pages without an adjacent numeric line no longer cancel the whole anchor
  group
- pages with nearby meaningful numeric context are counted as skipped numeric
  risk and retained
- suppression proceeds only when the remaining safe adjacent numeric
  occurrences still meet the existing repeated-page majority threshold
- numeric page values must still increase in extracted page order
- footer lines are removed only from the safe pages included in the accepted
  majority

This keeps the existing trailing-window, anchor, majority, page-order, and
numeric-risk safety boundaries. It does not change retention semantics,
auto-promote output, or broaden ingestion.

## Commands Run

- `git fetch origin main`
- `git merge --ff-only origin/main`
- `git worktree add .worktrees/cak-15-public-pdf-footer-audit -b audit/cak-15-public-pdf-footer-path origin/main`
- inspected `public_pdf` client, normalizer, CLI, run config, and DORA replay
  notes
- inspected the installed `knowledge-adapters/.venv` entry point and module
  paths
- live DORA PDF inspection scripts against the public source URL
- `make test PYTEST='.venv/bin/pytest tests/test_public_pdf_dora_regression_fixtures.py'`

## Recommended Next Action

Run the knowledge-vault milestone replay again from the updated branch after
merge, using the same one-source DORA ROI run config. Expected result:
candidate body output should change by removing 110 footer lines while
retaining the fused page-43 artifact and page-59 numeric-risk footer pair.

