# Public Webpage Chrome Regression Fixtures

Use deterministic, sanitized fixtures in
`tests/fixtures/public_webpage/article_chrome_cases.json` as the primary
iteration loop for public webpage chrome suppression.

The fixture area captures small article-body-plus-chrome shapes for:

- subscription and sign-in prompts
- share prompts
- comments and discussion placeholders
- footer/legal text
- platform promotion text
- retained article body text with replay-quality boundary metadata
- chrome-only diagnostic replay shapes where no reviewable article text remains

The adapter does not summarize article bodies, claim copyright or reuse
permission, change retention semantics, or make near-full article extraction
promotion-ready. Replay-quality metadata is informational only and helps
reviewers distinguish deterministic page-chrome suppression from retained
candidate article body text. The shared replay classification reports
`review-ready` for retained article text and `diagnostic-only` when suppression
leaves no content worth reviewing; unreviewed public webpage candidates remain
`unsafe-to-promote`.
