# Confluence Adapter

## Purpose

The Confluence adapter fetches content from a target Confluence page or page tree and normalizes it into local markdown artifacts with metadata.

This adapter is the first implementation of the generic adapter contract for `knowledge-adapters`.

## Initial Scope

The first version should support:

- page URL or page ID as input
- runtime-provided auth
- single page fetch
- optional tree mode after single-page flow works
- markdown plus metadata output
- manifest generation
- dry-run mode

## Runtime-Specific Inputs

These values must be provided at runtime and must not be committed:

- Confluence base URL
- auth method and credential reference
- target page URL or page ID
- output directory
- optional fetch mode and limits

## Responsibilities

The adapter should:

1. resolve page input into a canonical page ID
2. fetch source content and metadata
3. normalize source content into markdown
4. write stable local artifacts
5. update a manifest with fetch results

## Non-Goals for Initial Version

- browser automation
- attachments
- comments
- complete macro fidelity
- every auth flow
- publishing to external systems

## Suggested Next Steps

1. define CLI inputs
2. define config model
3. implement target resolution
4. implement fixture-based fetch path
5. normalize to markdown
6. write output files and manifest
7. add tests