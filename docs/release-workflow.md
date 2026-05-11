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
   GitHub release; this also runs the repository's canonical `make check`
   validation:

   ```bash
   make release-check VERSION=0.8.1
   ```

4. after the release PR lands, publish the post-merge tag and GitHub release:

   ```bash
   make release-publish VERSION=0.8.1
   ```

## Release Recovery

If `make release-publish VERSION=X.Y.Z` creates a local or remote `vX.Y.Z` tag
but fails before the GitHub release is created, inspect the partial state before
rerunning release commands:

```bash
make release-recover VERSION=X.Y.Z
```

The recovery target reports whether the local tag, remote tag, and GitHub
release exist. It does not create, delete, move, or push tags.

If only the local tag exists and the publish should be retried from scratch, the
target prints the exact manual local deletion command:

```bash
git tag -d vX.Y.Z
```

If the remote tag exists but the GitHub release is missing, create the release
from the existing remote tag without creating, deleting, or moving tags:

```bash
make release-create-from-tag VERSION=X.Y.Z
```

Do not delete, recreate, or force-push a public release tag during this recovery
path. If the pushed tag points at the wrong commit, stop and handle it as an
explicit release correction.

## Notes

- Keep the tag format consistent as `vX.Y.Z`.
- `make release-publish` accepts `VERSION=X.Y.Z` or `VERSION=vX.Y.Z`, creates
  the annotated tag as `vX.Y.Z`, and uses the matching `## X.Y.Z` section from
  `CHANGELOG.md` as the GitHub release notes.
- Ensure the version, `CHANGELOG.md`, and tag all align before merging the
  release PR.
