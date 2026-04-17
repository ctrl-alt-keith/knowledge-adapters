# Adapter Specification

## Purpose

This document defines the contract for source adapters in this repository.

The initial implementation target is Confluence, but the contract is intended to be generic enough to support future adapters.

## Adapter Responsibilities

An adapter must:

1. accept runtime-provided source configuration

2. resolve a target into a canonical identifier

3. fetch content and relevant metadata from the source

4. normalize the result into the repository's local artifact format

5. persist outputs to a specified local directory

6. track state in a manifest or equivalent metadata file

7. report useful success/failure outcomes

8. avoid embedding environment-specific details in the repo

## Runtime Inputs

Adapters should accept, directly or indirectly, the following classes of input:

### Required

- source base URL or equivalent locator

- authentication method or credential reference

- target page/resource identifier

- output directory

### Optional

- fetch mode (`single`, `tree`)

- recursion depth

- manifest path

- dry-run flag

- update/since filters

- timeout/retry settings

## Configuration Principles

Configuration precedence should be:

1. CLI arguments

2. local config file outside the repo

3. environment variables

4. safe defaults

Environment-specific config must remain outside the repo.

## Canonical Adapter Flow

```text

config -> resolve -> fetch -> normalize -> persist -> report
```