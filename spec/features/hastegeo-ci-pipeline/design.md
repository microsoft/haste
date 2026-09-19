# Technical Design: hastegeo CI build and release pipeline

## Overview

The pipeline separates untrusted source execution from trusted repository and
Azure mutations. A read-only job builds and validates the wheel, passes it as
an Actions artifact, and a trusted default-branch workflow validates and
automatically publishes same-repository PR RCs. Stable releases publish
automatically on merge to `main`, gated only by the `HASTEGEO_PUBLISH_ENABLED`
kill switch — the branch ruleset's required PR review is the release approval.

## Architecture

```text
PR source (untrusted)
  |
  v
Build job [contents:read, persist-credentials:false]
  - resolve version from public release state
  - hatch build with explicit HASTE_SET_VERSION
  - tests + wheel metadata validation
  |
  v
Actions artifact: wheel + SHA256 + version + source SHA
  |
  v
Trusted publish job [contents:write, trusted base ref only]
  - verify same-repo/open/current PR SHA
  - enforce rc filename policy
  - validate wheel METADATA and checksum
  - reject an existing release asset
  - upload to haste-binaries
  |
  +--> ACR Tasks build training + imageryprep ONCE, in parallel
       tags: X.Y.ZrcN (exact wheel version)
  |
  +--> deploy workflow uses the same wheel + both image tags

Stable push:
  HASTEGEO_PUBLISH_ENABLED kill switch
  -> publish X.Y.Z + create/reconcile hastegeo-vX.Y.Z tag
```

## New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Version resolver | `.github/scripts/resolve_hastegeo_version.py` | Stable/RC selection and tag idempotency | Python |
| Wheel validator/publisher | `.github/scripts/publish_hastegeo_wheel.py` | Validate immutable asset and publish it | Python + `gh` |
| Resolver tests | `hastelib/tests/build/` | Version and publication policy tests | `unittest` |

## Modified Components

| Component | Path | Change |
|---|---|---|
| Hatch hook | `hastelib/haste_build.py` | Stamp explicit version; build only |
| Wheel workflow | `.github/workflows/hastegeo-build.yml` | Split build and publish credentials |
| Image workflow | `.github/workflows/docker-build-and-push.yml` | Avoid duplicate hastelib builds |
| Deploy workflow | `.github/workflows/deploy-apps.yml` | Validate exact wheel before Azure mutation |
| Deploy script | `.github/scripts/deploy_apps.sh` | Propagate Function publish failures |
| Cleanup | `.github/scripts/cleanup_rc_releases.py` | Fail-closed report/manual deletion |

## Version Contract

- The latest stable release asset is `hastegeo-X.Y.Z-py3-none-any.whl`.
- Default target is latest stable plus one patch.
- `HASTE_BUMP=minor|major` and `HASTE_SET_VERSION` remain explicit overrides.
- PR versions are canonical PEP 440 `X.Y.ZrcN`.
- Stable versions are `X.Y.Z`.
- A stable `hastegeo-vX.Y.Z` Git tag points to the source commit.
- If the current main SHA already has a valid hastegeo tag and asset, the
  workflow succeeds as a no-op.
- If the tag exists but the asset is missing, the same version is rebuilt.
- A tag at a different SHA or an existing mismatched asset is a hard failure.

## Trust Boundaries

### Build job

- `contents: read`
- `actions/checkout` uses `persist-credentials: false`
- no `GH_TOKEN`, Azure login, repository secrets, or environment secrets
- PR code may execute because producing an RC of that code is intentional
- no Docker image build occurs here; ACR produces the final image once

### Trusted RC publish job

- automatically runs for successful same-repository PR builds
- verifies the PR is still open and the built SHA is still current
- downloads the wheel artifact
- checks out only the trusted default branch for publisher code
- never imports or executes code from the wheel
- validates exact filename, ZIP structure, `METADATA`, version, source SHA,
  checksum, and channel
- uploads without clobbering
- publish jobs are serialized, but read-only builds remain concurrent; if two
  builds chose the same RC, the later publisher fails safely and is rerun to
  resolve the next RC

### ACR image job

- uses Azure OIDC after RC publication
- uses the configured RC GitHub Environment
- does not execute PR-owned shell scripts with Azure credentials
- submits the PR source context through trusted inline `az acr build` commands
- Docker build code does not receive the runner's Azure token
- builds each image once, tags it exactly `X.Y.ZrcN`, and locks the tag

## Deploy Behavior

The workflow accepts an optional `hastegeo_version`. It normalizes the value
with `packaging.version.Version`, constructs the canonical asset name, and
verifies the asset exists before Azure login or Function mutation. The deploy
script rewrites both Function requirements files and treats any non-zero
`func publish` exit as a deployment failure. For an RC, blank image-tag inputs
default to `hastegeo_version`; explicitly different RC tags are rejected.

## Cleanup Behavior

Scheduled runs only report deletion candidates. Manual deletion requires the
protected release environment. `--keep` must be non-negative, the configured
retain file must exist, and any GitHub query/delete failure aborts the run.

## Error Handling

| Error | Behavior |
|---|---|
| GitHub release query fails | Build fails; no local-version fallback |
| Existing wheel asset | Fail or no-op only when checksum/source identity matches |
| Concurrent builds choose the same RC | First publish wins; second fails without clobber and is rerun |
| RC publish races a stable release | RC is rejected when the stable target exists |
| Invalid wheel filename/METADATA | Publish rejected |
| Stable tag points elsewhere | Publish rejected |
| Azure Function publish fails | Workflow fails |
| Missing retain file | Cleanup fails |
| Fork PR | Build/test only; no publish or image push |

## Configuration

| Setting | Purpose |
|---|---|
| `HASTEGEO_RC_ENVIRONMENT` repository variable | Selects the environment providing RC ACR OIDC/secrets |
| `HASTEGEO_RC_PUBLISH_ENABLED` repository variable | RC kill switch (`false` disables; absent enables) |
| `hastegeo-release` environment | Required reviewer approval for destructive RC deletion (`rc-cleanup.yml`) |
| `HASTEGEO_PUBLISH_ENABLED` repository variable | Stable publication enablement / kill switch |
| `HASTEGEO_RELEASE_APPROVAL_CONFIGURED` repository variable | Admin confirmation that required reviewers are active; gates RC deletion only |
| `HASTE_BUMP` | Patch(default), minor, or major target |
| `HASTE_SET_VERSION` | Exact version override |
