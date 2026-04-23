# Release Workflow

## Purpose

This document captures the lightweight release steps for
`knowledge-adapters`.

Keep the release arc focused on versioning and release metadata. Avoid mixing
unrelated cleanup into the same PR.

## Release Steps

1. ensure `main` is clean and up to date
2. confirm the version bump is present
3. confirm `CHANGELOG.md` is updated
4. run `make check`
5. create a release branch if needed
6. merge the release PR
7. create a tag in the format `vX.Y.Z`
8. push the tag
9. create the GitHub release

## Notes

- Keep the tag format consistent as `vX.Y.Z`.
- Ensure the version, `CHANGELOG.md`, and tag all align.
