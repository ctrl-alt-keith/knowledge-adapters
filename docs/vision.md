# Vision

## Problem

Knowledge needed by LLM workflows often lives in multiple systems with very different access patterns, structures, and output formats.

Examples include:

- Confluence

- local markdown notes

- Google Docs

- Git repositories

These sources are often hard to use directly because they differ in:

- authentication

- hierarchy and navigation

- update detection

- formatting quality

- metadata shape

- API ergonomics

## Goal

Create a reusable adapter pattern that converts heterogeneous knowledge sources into stable local artifacts that can be consumed by downstream LLM tooling.

The key idea is:

```text

source -> fetch -> normalize -> persist
```