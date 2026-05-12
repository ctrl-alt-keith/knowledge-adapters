# Public PDF DORA Regression Fixtures

This directory contains sanitized, DORA-derived public PDF extraction fixtures
for deterministic normalization tests.

The fixtures are intentionally small snippets, not retained report content. They
capture mechanical extraction shapes observed during DORA replay work so
normalization behavior can be iterated inside `knowledge-adapters` without using
knowledge-vault replay as the primary feedback loop.

Knowledge-vault replay remains milestone and integration validation for full
adapter behavior, destination wiring, and end-to-end candidate artifact review.
