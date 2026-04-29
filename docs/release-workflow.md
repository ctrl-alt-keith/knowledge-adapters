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
7. sync `main` after the merge:

   ```bash
   git switch main
   git pull --ff-only origin main
   ```

8. publish the post-merge tag and GitHub release:

   ```bash
   make release-publish VERSION=0.8.1
   ```

## Notes

- Keep the tag format consistent as `vX.Y.Z`.
- `make release-publish` accepts `VERSION=X.Y.Z` or `VERSION=vX.Y.Z`, creates
  the annotated tag as `vX.Y.Z`, and uses the matching `## X.Y.Z` section from
  `CHANGELOG.md` as the GitHub release notes.
- Use `make release-check VERSION=0.8.1` to validate the post-merge release
  prerequisites without creating a tag or GitHub release.
- Ensure the version, `CHANGELOG.md`, and tag all align before merging the
  release PR.
