# Public Webpage Chrome Regression Fixtures

Use deterministic, sanitized fixtures in
`tests/fixtures/public_webpage/article_chrome_cases.json` and
`tests/test_public_webpage_target_discovery.py` as the primary iteration loop
for public webpage chrome suppression, source-intent assessment, and bounded
target discovery.

The fixture area captures small article-body-plus-chrome shapes for:

- subscription and sign-in prompts
- share prompts
- comments and discussion placeholders
- footer/legal text
- platform promotion text
- retained article body text with replay-quality boundary metadata
- chrome-only diagnostic replay shapes where no reviewable article text remains
- wrapper, lead-form, download-landing, and resource-catalog page shapes
- operational-research source shapes such as redirected historical reports,
  mutable research indexes, commercial book landings, stable publication URLs,
  and table-of-contents/chapter navigation pages
- same-page target discovery when exactly one high-confidence report asset is
  present
- no-selection safety when targets are missing or ambiguous
- false-positive safety for substantive pages that mention downloads, contact
  sales, navigation, or footer links in ordinary body context

The adapter does not summarize article bodies, claim copyright or reuse
permission, change retention semantics, or make near-full article extraction
promotion-ready. Replay-quality metadata is informational only and helps
reviewers distinguish deterministic page-chrome suppression from retained
candidate article body text and from likely wrong capture targets.

The source-intent assessment reports bounded operational labels such as
`target_shape_assessment`, `possible_wrapper_page`,
`possible_lead_form_page`, `possible_download_landing_page`,
`commercial_landing_page_detected`, `mutable_index_page_detected`,
`chapter_navigation_source_detected`, `historical_report_redirect_detected`,
`stable_research_asset_detected`, `canonical_target_resolution_status`,
`canonical_source_confidence`, `substantive_content_confidence`, and
`likely_target_mismatch`. When a mismatch is detected, target discovery is
limited to links and metadata already present on the fetched page. It does not
crawl, search, summarize, or choose among ambiguous candidates.

Automatic target fetch is allowed only when one same-page target satisfies the
selection guards:

- public HTTP(S) URL
- same official host family as the fetched page
- report, document, download, or PDF semantics
- high-confidence title or identity match
- one clear winner after rejecting marketing, nav, social, legal, and catalog
  links

Selected PDFs route through the existing `public_pdf` adapter. Selected HTML
targets route through `public_webpage` with target discovery disabled to avoid
multi-hop crawling. If no high-confidence target exists, or multiple plausible
targets conflict, the adapter keeps the wrapper capture as
`likely-wrong-capture-target` and records candidate targets plus the selection
reason for operator review.

Live observation on May 13, 2026: the Google Cloud 2025 DORA page at
`https://cloud.google.com/devops/state-of-devops` was detected as
`likely_wrong_capture_target`, selected exactly one embedded same-page PDF
target, and routed replay through the public PDF adapter:
`https://services.google.com/fh/files/misc/2025_state_of_ai_assisted_software_development.pdf`.

Operational-research observations on May 13, 2026: IT Revolution Accelerate and
ACM Queue SPACE returned HTTP 403 challenge pages to direct replay requests;
the Puppet 2021 State of DevOps URL redirected to the current State of DevOps
hub; Microsoft Research developer tools returned HTTP 403; Team Topologies
served a commercial/book landing shape; METR research and GitHub Octoverse
served mutable research/index pages; and the Google SRE workbook table of
contents served a stable chapter-navigation page.

The shared replay classification reports `review-ready` for retained or routed
substantive target content, `likely-wrong-capture-target` for retained wrapper
content that needs source-target review, and `diagnostic-only` when suppression
leaves no content worth reviewing. Unreviewed public-source candidates remain
`unsafe-to-promote`.
