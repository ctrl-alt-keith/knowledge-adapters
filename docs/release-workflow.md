# Release Workflow

## Purpose

This document is the thin release adapter for `knowledge-adapters`.

Keep the release arc focused on versioning and release metadata. Avoid mixing
unrelated cleanup into the same PR.

For shared branch, PR, validation, and current-main workflow, follow
`AGENTS.md` and `ai-workflow-playbook/docs/start-here.md`.

## Release Steps

1. confirm the version bump is present
2. confirm `CHANGELOG.md` is updated
3. validate the post-merge release prerequisites without creating a tag or
   GitHub release:

   ```bash
   make release-check VERSION=0.8.1
   ```

4. after the release PR lands, publish the post-merge tag and GitHub release:

   ```bash
   make release-publish VERSION=0.8.1
   ```

## Notes

- Keep the tag format consistent as `vX.Y.Z`.
- `make release-publish` accepts `VERSION=X.Y.Z` or `VERSION=vX.Y.Z`, creates
  the annotated tag as `vX.Y.Z`, and uses the matching `## X.Y.Z` section from
  `CHANGELOG.md` as the GitHub release notes.
- Ensure the version, `CHANGELOG.md`, and tag all align before merging the
  release PR.
