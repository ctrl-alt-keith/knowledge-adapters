# Public PDF Footer And Page-Number Noise

This note records measurement and design guidance for public PDF footer and
page-number normalization. It is diagnostic only: it does not approve candidate
content, change retention semantics, promote material, or add new suppression
rules.

## Current Measurement

Public PDF replay-quality metadata includes
`footer_page_number_noise_diagnostics`, measured after URL replay-noise repair
and before the existing repeated footer suppression pass. The diagnostic block
records:

- repeated trailing footer block and signature counts inside the last three
  nonempty lines of each extracted page
- bare numeric line counts, including whether those lines appear in the trailing
  footer candidate window
- repeated bare numeric trailing signatures that look page-number-like but are
  not sufficient by themselves to prove noise
- bare numeric lines adjacent to meaningful numeric context, such as table,
  calculator, value, cost, score, or formula-like lines
- footer-like page-number text that appears before the trailing candidate
  window, which can happen when `pypdf` places a visual footer in the middle of
  reading order

The metadata is deterministic and informational. Counts are review aids, not
retention decisions.

## Synthetic Cases

Safe repeated footer blocks look like a stable report footer plus changing page
numbers at the bottom of pages:

```text
Executive summary
DORA Report
1
```

```text
Key findings
DORA Report
2
```

Unsafe numeric table or calculator rows can look page-number-shaped in extracted
text even when they are meaningful values:

```text
Calculator
Input value 10
15
Output value 25
```

Footer-like text can appear mid-page in `pypdf` reading order:

```text
Intro
DORA Report | 1
Body
Metric 5
Detail A
Closing A
```

Bare page-number-shaped lines adjacent to report values are risky because the
same line shape can be either visual page chrome or meaningful numeric content:

```text
Table
Metric value 12
1
Total value 13
```

## Proposed Future Rules

A future implementation PR should keep footer/page-number suppression narrow:

- suppress repeated multi-line trailing footer blocks only when the nonnumeric
  footer text repeats by page position across the required page majority
- treat bare numeric lines as suppressible only when anchored to a repeated
  nonnumeric footer block on the same pages and at adjacent trailing positions
- do not suppress a bare numeric line solely because it repeats as a normalized
  `#` signature
- do not suppress footer-like text found outside the trailing candidate window
  unless a later design can prove the extraction order case without touching
  table, calculator, figure, or report body content
- do not suppress numeric lines adjacent to meaningful numeric context unless a
  stronger source-specific signal exists
- keep all rules deterministic and source-agnostic unless a future PR
  explicitly documents source-specific behavior

## Non-Goals

This slice does not add new suppression behavior, repair ordinary prose
hyphenation, infer semantic sections, auto-promote candidates, rank document
quality, or assert that a diagnostic count is safe to remove.
