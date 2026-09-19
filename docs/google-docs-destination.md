# Google Docs Publication

## Status

`knowledge-adapters` is the operator-facing implementation home for the
explicit Google Docs publication path. This supersedes the earlier separate
destination-layer recommendation, without changing Publication authority.

## Boundary

The local workflow remains:

```text
source acquisition -> normalization -> bundle -> explicit publish
```

Each arrow is a semantic boundary. A successful acquisition, configured bundle,
or `publishes:` entry creates no authorization to publish. `knowledge-adapters
run` executes only `runs:`; `knowledge-adapters bundle` renders only local
bundle files. Only this separately invoked action can call Google APIs:

```text
knowledge-adapters publish --config runs.yaml --publish <name>
```

The operator selects the exact configured publication and thereby supplies the
consequential action. Authentication proves provider access, not publication
authorization. The result is a publication receipt, not editorial approval or
retention.

## Configuration

`publishes:` is local configuration beside `runs:` and `bundles:`. Each entry
names an existing bundle and may specify a title, Drive folder, and Desktop
OAuth paths. If `title` is omitted, the explicit publish action derives it from
the existing bundle output filename without its final extension. This derives
display text only; it neither invokes publication nor changes authorization.

```yaml
publishes:
  - name: review-pack-doc
    bundle: review-pack
    # title: Review Pack
    # folder_id: "folder-id"
    # oauth_client_file: /secure/google-desktop-client.json
    # oauth_token_file: /secure/knowledge-adapters-google-token.json
```

Publishing never executes or renders the named bundle. It reads that existing
local output only after the operator explicitly selects the publish entry.

## Installation

The Google client libraries are an opt-in `publish` extra rather than a base
dependency, so operators who only acquire and bundle do not carry them:

```bash
pip install 'knowledge-adapters[publish]'
```

Without the extra, configuration parsing and `--dry-run` still work, and a real
publish fails closed with installation guidance rather than a partial attempt.

## Google authentication and safety

ADC remains the default. Installed-app Desktop OAuth is opt-in and requires
both caller-selected files. The publisher requests Docs scope and adds Drive
file scope only for folder creation. It re-consents when a stored token lacks
required scopes; tokens are written atomically at mode `0600` and unsafe token
files are rejected. Diagnostics use allowlisted status/reason classification
and never render provider response bodies, messages, or tokens.

## Non-goals

This path creates a new document from a caller-selected local bundle. It does
not add sharing, permission management, document updates, lifecycle state,
background sync, acquisition, or implicit publication.
