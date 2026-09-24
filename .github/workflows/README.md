# GitHub Actions Workflows Documentation

This directory contains GitHub Actions workflows for the HASTE project, focused on building and pushing Docker images to Azure Container Registry (ACR) using OpenID Connect (OIDC) authentication and semantic versioning.

## hastegeo Wheel and Versioned Images

`hastegeo-build.yml` handles changes under `hastelib/`:

1. A trusted read-only resolver chooses the next dev, RC, or stable version.
2. An untrusted-source build job runs without write credentials and uploads the
   validated wheel as an Actions artifact.
3. `hastegeo-publish.yml`, loaded from `main` through `workflow_run`, validates
   the artifact again and automatically publishes same-repository PR RCs.
4. ACR Tasks builds `hastetraining` and `hasteimageryprep` once, in parallel,
   with the exact same tag as the wheel (`X.Y.ZrcN`).
5. The workflow comments the matching `hastegeo_version`,
   `training_image_tag`, and `imageprep_image_tag` on the PR.

Stable releases create `hastegeo-vX.Y.Z` tags, making reruns of the same source
commit a no-op. Stable publication is automatic: merging a PR into `main` that
touches `hastelib/` publishes the next **patch** wheel, because the review
required to land that commit is the release approval. Set
`HASTEGEO_PUBLISH_ENABLED=true` to enable it; set it to anything else to halt
stable publication.

Minor and major stable releases have no automated path today. The publisher
derives the channel from the upstream event — `pull_request` is `rc`, `push` is
`release`, `workflow_dispatch` is `dev` — so a dispatch can never publish a
stable wheel however its `channel` input was set.

That guard fails closed rather than quietly: dispatching with `channel: rc` or
`release` builds a wheel the publisher will not accept, because it looks for
the `.devN` name it resolved and finds an `rcN` or stable one instead. **Publish
hastegeo wheel and images** then ends **red** on its artifact-name check. The
wheel is still attached to the build run as an artifact, so use an rc/release
dispatch only to validate that a version resolves and builds — and expect the
failed publish run that follows.

### Dev Wheels: Iterating on a Function App

To change `hastegeo` and test it in a deployed function app without minting a
release candidate, dispatch **Build hastegeo wheel** on your branch with
`channel: dev`. It publishes `X.Y.Z.devN` to `haste-binaries`, which
`deploy-apps.yml` accepts as `hastegeo_version`.

An RC would work too, but drags in artifacts you do not need: `deploy-apps.yml`
requires image tags to equal any `rc` wheel version exactly, so an RC deploy
also needs matching locked images built. A `.devN` version contains no `rc`
substring and carries no such coupling, so it deploys against whatever images
the environment already runs. PEP 440 orders `1.0.2.dev1 < 1.0.2rc1 < 1.0.2`,
so a dev wheel can never shadow a real release.

No images are built for a dev wheel, so leave both image tags **blank**:
`deploy-apps.yml` then reuses whatever the target environment is already
running, read back from `AZURE_BATCH_DOCKER_IMAGE` on the queue app. Only a
first deploy to an environment with no images yet needs them passed.

Dev wheels are immutable, never tagged, and pruned by `rc-cleanup.yml` on the
same rules as RCs, counted separately so rapid dev iteration never evicts a
release candidate. Add a filename to `.github/rc-retain.txt` to pin one an
environment is still running. Dev publication is automatic unless
`HASTEGEO_DEV_PUBLISH_ENABLED=false`.

> For a faster loop that needs no CI at all, the function app requirements
> default to `-e ../../hastelib`, so `func start` runs your working tree
> directly. Reach for a dev wheel when you need the *deployed* environment —
> managed identity, live queue triggers, real Batch submission.

RC publication is automatic unless `HASTEGEO_RC_PUBLISH_ENABLED=false`.
Fork PRs remain build-only. The RC image environment is selected through
`HASTEGEO_RC_ENVIRONMENT`, keeping environment names out of the workflow.
The protected `hastegeo-release` environment and the
`HASTEGEO_RELEASE_APPROVAL_CONFIGURED` variable still gate the destructive RC
deletion job in `rc-cleanup.yml`.

## Docker Build and Push Workflow

### Overview

The `docker-build-and-push.yml` workflow automates the building and pushing of Docker images to Azure Container Registry using ACR Tasks. It implements semantic versioning for release management.

### Supported Docker Images

The workflow can build the following Docker images:

- **Training Image** (`hastetraining`): Located in `docker/training/`
- **Imagery Prep Image** (`hasteimageryprep`): Located in `docker/imageryprep/`
- **All Images**: Both training and imagery prep images

### Trigger Methods

#### 1. Pull Request Triggers (Automatic)

```yaml
on:
  pull_request:
    branches:
      - main
```

**When**: Automatically triggered for Docker-only changes. If `hastelib/`
changes, `hastegeo-build.yml` owns the coherent wheel and image build instead.

**Default Behavior**:
- **Image Directory**: only the changed Docker image
- **Tag**: `{TAG_PREFIX}-rc{PR_NUMBER}` (e.g., `1.0.1-rc123`)

#### 2. Manual Workflow Dispatch

```yaml
on:
  workflow_dispatch:
    inputs:
      image_dir:         # choice: all, training, imageryprep
      image_tag:         # string: custom tag
```

**When**: Manually triggered from the GitHub Actions UI for production releases,
or to build images from an arbitrary branch.

**Parameters**:
- **Image Directory**: Choose from dropdown (`all`, `training`, `imageryprep`)
- **Custom Tag**: Text input for custom tag (default: `test-manual`)

**How to Use**:
1. Go to GitHub Actions tab
2. Select "Build and Push Docker Images" workflow
3. Click "Run workflow" and pick the branch to build
4. Choose parameters and run

**Building is unconstrained**: any branch, any tag string. `image_tag` is free
text, so throwaway tags like `meygha-test-3` are fine and expected.

**Deploying what you built** is governed by `deploy-apps.yml`, not here.
Leaving an input blank does **not** mean the same thing for the wheel as it
does for the images:

| Input | Blank means |
|---|---|
| `hastegeo_version` | **the latest stable wheel** — *not* the one currently deployed |
| `training_image_tag` / `imageprep_image_tag` | **keep the image the app is running** |

The asymmetry is forced, not a choice. The image tag is stored on the app as
`AZURE_BATCH_DOCKER_IMAGE`, so the deploy can read it back — off the app it is
about to deploy, the API app for `funcapi` and the queue app for `funcqueue`
and `all`. The wheel is pinned into `requirements.txt` at deploy time and
recorded nowhere, so there is nothing to read back and no way to know which
wheel an app is running.

**Consequence worth knowing:** a blank `hastegeo_version` moves the function
apps onto the latest stable wheel, even when you are deploying a branch that
changed no Python at all. Pin it explicitly if you need the deployed wheel to
stay put — and note this is what silently reverts a `.devN` escape hatch.

Each app that installs the wheel is now tagged `hastegeo_version=<version>` in
Azure, alongside the existing `env` and `deployed_version` tags, so you can at
least *see* what an environment is running without inspecting its
`requirements.txt`. Apps with no hastegeo line, such as titiler, are not
tagged. Nothing reads the tag back yet — making blank mean "keep the deployed
wheel" is future work.

Once a wheel version is chosen, the image tags are constrained only for an RC:

| `hastegeo_version` being deployed | Image tags |
|---|---|
| blank (latest stable) or `X.Y.Z` | anything, or blank to keep the running image |
| `X.Y.ZrcN` | must match the wheel version exactly |
| `X.Y.Z.devN` | anything, or blank to keep the running image |

To deploy a custom-tagged test image, pass `training_image_tag` /
`imageprep_image_tag` explicitly. The only refused combination is a custom
image alongside an RC wheel: the RC channel exists to ship a wheel and its
images as one locked, coherent set, and mixing a hand-tagged image into it
defeats that. For RC testing, let the PR pipeline in `hastegeo-publish.yml`
build the matching wheel and images instead.

A first deploy to an environment with no images yet has nothing to inherit, so
it fails with an explicit message rather than guessing.

Note that `deploy_apps.sh` interpolates the tag into `hastetraining:<tag>`
without checking that it exists in ACR, so a typo deploys cleanly and only
fails later when a Batch task tries to pull the image.

#### 3. Release Builds

To build images for a product release, **dispatch on the release tag** — the
ref dropdown lists tags as well as branches — and enter that release version as
the image tag:

| Field | Value |
|---|---|
| Ref (dropdown) | `v3.0.0` |
| `image_dir` | `all` |
| `image_tag` | `3.0.0` |

**Result**: `hastetraining:3.0.0` and `hasteimageryprep:3.0.0`, built from the
source at `v3.0.0`.

The image tag tracks the **product** release, not hastegeo's version. Those
numbers move independently on purpose: a release cut for a funcapp-only change
still gets its own image tag even though hastegeo did not change.

Because `deploy-apps.yml` defaults image tags to the resolved *hastegeo*
version, deploying a product-tagged image means passing `training_image_tag`
and `imageprep_image_tag` explicitly. That default is unchanged and still
correct for the RC path, which requires wheel and image tags to match.

Building from a tag while leaving `image_tag` at the `test-manual` placeholder
fails the run rather than publishing release code to a throwaway tag.

### hastegeo Version in Images

**There is no input for this, by design.** Both Dockerfiles `COPY
hastelib/src/hastegeo` from the checked-out tree instead of installing a wheel,
and set `PYTHONPATH=/app` to import it. The hastegeo in an image is therefore
*always* the source of the ref being built — this workflow cannot build an
image against a published wheel or another branch's hastegeo. The source tree
ships the development marker `0.0.0+local`, so the build stamps `__about__.py`
before handing the context to ACR:

| Build | Stamped version | Resolved from |
|---|---|---|
| Tag | `1.0.42` | highest `hastegeo-v*` tag merged into the tag |
| Tag with no `hastegeo-v*` reachable | `0.0.0+v2.0.0.<sha>` | ref name + sha, with a warning |
| Branch / PR | `0.0.0+<branch>.<sha>` | ref name + sha |

The tag case uses the same rule as [`release.yml`](release.yml)'s "Resolve the
matching hastegeo wheel" step, so an image built from `v3.0.0` reports the same
hastegeo version its release notes cite.

The stamp is always **derived, never typed**. Nothing downstream verifies that
a stamp matches the code it was applied to, so a hand-entered `1.0.42` could
make a WIP image indistinguishable at runtime from a real release. Restricting
real versions to tag builds means an in-flight `hastelib` change can never be
stamped with a release version it is merely descended from, and the `0.0.0+`
prefix keeps every branch image self-evidently non-release.

Note this is *only* a label on the contents. Wheels themselves — and the locked
RC images — come from `hastegeo-publish.yml`, which stamps the version it
resolved for that exact sha.

### Semantic Versioning Strategy

#### Repository Variable Required

Create a repository variable named:

- **Name**: `TAG_PREFIX`
- **Value**: `1.0.1` (or your current semantic version base)

**Setup Instructions**:
1. Go to repository settings
2. Navigate to "Secrets and variables" → "Actions"
3. Click on "Variables" tab
4. Click "New repository variable"
5. Name: `TAG_PREFIX`, Value: `1.0.1`

#### Tag Generation Logic

```yaml
IMAGE_TAG: ${{ github.event.inputs.image_tag || format('{0}-rc{1}', vars.TAG_PREFIX, github.event.number) }}
```

**Logic**:
- **Manual dispatch**: Uses custom input tag
- **PR to main**: Uses `{TAG_PREFIX}-rc{PR_NUMBER}` format

#### Tag Examples

| Trigger Type | Input | Generated Tag | Example |
|--------------|-------|---------------|---------|
| Manual Dispatch | Custom tag: `v2.0.0` | `v2.0.0` | `hastetraining:v2.0.0` |
| Manual Dispatch | Default | `test-manual` | `hastetraining:test-manual` |
| PR #123 to main | N/A | `1.0.1-rc123` | `hastetraining:1.0.1-rc123` |

### Security and Authentication

#### OIDC Configuration

The workflow uses OpenID Connect for secure, keyless authentication to Azure:

```yaml
- name: Azure Login
  uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

#### Required Secrets

Configure these secrets in your GitHub repository:

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `AZURE_CLIENT_ID` | Azure Application (client) ID | `12345678-1234-1234-1234-123456789012` |
| `AZURE_TENANT_ID` | Azure Directory (tenant) ID | `87654321-4321-4321-4321-210987654321` |
| `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID | `abcdef12-3456-7890-abcd-ef1234567890` |
| `ACR_NAME` | Azure Container Registry name | `myregistry` |

#### Required Repository Variables

| Variable Name | Description | Example |
|---------------|-------------|---------|
| `TAG_PREFIX` | Semantic version prefix for RC builds | `1.0.1` |

#### hastegeo Publication Variables

Repository-level Actions variables gating `hastegeo-publish.yml` and
`rc-cleanup.yml`. Note the asymmetry: the two prerelease channels are **on
unless disabled**, while stable publication and the destructive cleanup are
**off unless explicitly enabled**.

| Variable Name | Default when unset | Effect |
|---------------|--------------------|--------|
| `HASTEGEO_DEV_PUBLISH_ENABLED` | enabled | Set to `false` to stop publishing dev wheels. The build still runs and attaches the wheel as an artifact; `prepare` then **fails** rather than skipping quietly, because a dev build is always an explicit dispatch. |
| `HASTEGEO_RC_PUBLISH_ENABLED` | enabled | Set to `false` to stop publishing RC wheels on PRs. Skips silently — RC publication is automatic, so annotating every PR would be noise. |
| `HASTEGEO_PUBLISH_ENABLED` | **disabled** | Must equal `true` for stable publication on merge to the default branch. Also required by the `rc-cleanup.yml` deletion job. |
| `HASTEGEO_RC_ENVIRONMENT` | **no images** | Name of the GitHub Environment used to build locked RC images. Empty or unset skips `build-rc-images`, keeping environment names out of the workflow. |
| `HASTEGEO_RELEASE_APPROVAL_CONFIGURED` | **disabled** | Must equal `true` to allow the destructive prerelease deletion job in `rc-cleanup.yml`. Deliberately *not* read by the publish jobs. |

Comparisons are case-insensitive, but only the literal string `false` disables
the first two — `0`, `no`, and `off` leave them enabled.

#### Permissions

The workflow requires the following permissions:

```yaml
permissions:
  id-token: write    # For OIDC authentication
  contents: read     # For repository checkout
  pull-requests: read # For PR information
```

### Build Process

#### Script Execution

The workflow delegates actual building to the `build_and_push_images.sh` script:

```bash
bash .github/scripts/build_and_push_images.sh -i "$IMAGE_DIR" -t "$IMAGE_TAG" -a "$ACR_NAME"
```

#### ACR Tasks Integration

The script uses Azure Container Registry Tasks (`az acr build`) for building:

```bash
az acr build \
  --registry "$ACR_NAME" \
  --image "$image_tag_for_acr" \
  --file "$dockerfile_relative_path" \
  "$REPO_DIR"
```

#### Benefits of ACR Tasks

- **Cloud-native building**: No local Docker daemon required
- **Automatic pushing**: Built images are automatically pushed to ACR
- **Build logs**: Comprehensive build logs available in Azure
- **Security**: Images never leave Azure environment during build

### Image Naming Convention

#### Format

```
{ACR_NAME}.azurecr.io/haste{image_type}:{tag}
```

#### Examples

- `myregistry.azurecr.io/hastetraining:v2.0.0`
- `myregistry.azurecr.io/hasteimageryprep:1.0.1-rc123`
- `myregistry.azurecr.io/hastetraining:test-manual`

### Usage Examples

#### Example 1: Production Release (Manual)

1. Go to Actions → Build and Push Docker Images
2. Click "Run workflow"
3. Select `all` for image directory
4. Enter `v2.0.0` for image tag
5. Click "Run workflow"

**Result**: Builds `hastetraining:v2.0.0` and `hasteimageryprep:v2.0.0`

#### Example 2: Development Release Candidate (Automatic)

Create a PR against the `main` branch.

**Result**: Automatically builds both images with tag `1.0.1-rc{PR_NUMBER}` (e.g., `hastetraining:1.0.1-rc123`)

### Error Handling and Debugging

#### Script Features

- **Colored Output**: Different colors for info, success, warning, and error messages
- **GitHub Actions Integration**: Proper `::notice::`, `::warning::`, and `::error::` annotations
- **Validation**: Input validation for all parameters
- **Cleanup**: Docker system cleanup before builds
- **Detailed Logging**: Comprehensive logging of all operations

#### Common Issues and Solutions

1. **Authentication Failures**
   - Verify OIDC secrets are correctly configured
   - Check Azure service principal permissions

2. **Image Build Failures**
   - Check Dockerfile syntax
   - Verify base image availability
   - Review ACR task logs in Azure portal

3. **Variable Access Issues**
   - Verify `TAG_PREFIX` repository variable is created
   - Check variable value is in correct semantic version format

### Troubleshooting

#### Workflow Not Triggering

- Check branch names in trigger configuration
- Verify PR is against the `main` branch
- Ensure manual dispatch is run with proper parameters

#### Build Failures

- Check script permissions and syntax
- Verify Dockerfile paths and syntax
- Review ACR permissions and quotas
- Check Azure subscription limits

#### Authentication Issues

- Verify OIDC configuration in Azure
- Check secret values in GitHub
- Ensure service principal has ACR permissions

### Maintenance

#### Regular Tasks

1. **Update Dependencies**: Keep GitHub Actions versions updated
2. **Review Secrets**: Rotate Azure credentials periodically
3. **Clean Up Images**: Remove old test images from ACR
4. **Update TAG_PREFIX**: Increment semantic version as needed

---

## Deploy Apps Workflow

### Workflow Overview

The `deploy-apps.yml` workflow deploys the HASTE application suite to Azure, including Function Apps, Static Web Apps, and configures the necessary cloud infrastructure. All per-target configuration (region, resource naming, custom domain, etc.) is sourced from **GitHub Environments** so the same workflow can deploy to any number of targets without code changes.

### Trigger

Manual trigger only using `workflow_dispatch` from the GitHub Actions interface.

### Input Parameters

| Parameter | Description | Required | Type |
|-----------|-------------|----------|------|
| `environment` | Deployment target — must match a configured GitHub Environment | Yes | string |
| `training_image_tag` | Training Docker image tag to deploy | Yes | string |
| `imageprep_image_tag` | Image prep Docker image tag to deploy | Yes | string |
| `app_tag` | Application version tag | Yes | string |

If the typed `environment` value does not match a configured GitHub Environment, the job fails immediately with a clear error from GitHub.

### Required Secrets

The recommended posture is **full isolation**: each deployment target is backed by its own Azure subscription, service principal, container registry, batch account, and resource groups, with secrets defined at GitHub Environment scope. This contains blast radius — a compromised workflow run for one environment cannot reach any other environment's credentials or resources.

**Repository secret** (only one secret is truly shared across all environments — Settings → Secrets and variables → Actions → Repository secrets):

| Secret | Description |
|--------|-------------|
| `AZURE_TENANT_ID` | Azure Active Directory tenant ID (same across all environments in this fork) |

**Environment secrets** (one set per target — Settings → Environments → `<env>` → Environment secrets):

| Secret | Description |
|--------|-------------|
| `AZURE_CLIENT_ID` | OIDC service principal client ID dedicated to this environment |
| `AZURE_SUBSCRIPTION_ID` | Subscription hosting this environment's resources |
| `ACR_NAME` | Azure Container Registry hosting the training and imageprep images for this environment |
| `BATCH_ACCOUNT` | Azure Batch account for this environment |
| `SHARED_RESOURCE_GROUP` | Resource group hosting cross-service shared resources for this environment |
| `RESOURCE_PREFIX` | Naming prefix for Azure resources in this environment |
| `RESOURCE_SUFFIX` | Stable random suffix for resource names — generate once with `openssl rand -hex 3` when bootstrapping the environment and keep constant across redeploys |
| `LOCATION` | Azure region for this environment (e.g. `eastus`) |
| `STATIC_APP_DOMAIN` | Custom domain for the Static Web App in this environment |
| `EMAIL_CONNECTION_STRING` | Azure Communication Services connection string for email |
| `ENVIRONMENT_TYPE` | Application environment type (e.g. `dev`, `staging`, `prod`). Surfaces as the `env=` tag on Azure resources and as an app setting on the Function App, where it controls runtime behavior (batch node type, etc.). Distinct from the GitHub Environment name — multiple GitHub Environments can share the same `ENVIRONMENT_TYPE` if they're meant to behave identically at runtime |

> **On sharing infrastructure across environments:** Some operators choose to share a single Azure Container Registry, Batch account, or shared resource group across multiple environments to reduce cost or operational overhead. The workflow supports that — move just those secrets to repository scope and they apply to every environment (GitHub looks up secrets at environment scope first and falls back to repository scope, so the YAML works either way). Be deliberate about which resources you share: a single compromised pipeline run gains access to whatever the shared resource holds, expanding blast radius across all environments that use it. The template defaults to isolation; sharing is an operator's informed tradeoff.

### Setting Up a New Environment

1. **Provision dedicated Azure resources** for this environment, following the fully-isolated blueprint: an Azure subscription (or at minimum a dedicated set of resource groups), a dedicated App Registration with federated credentials matching the GitHub Environment (`repo:<org>/<repo>:environment:<env-name>`), Azure RBAC scoped only to this environment's resources, and dedicated ACR / Batch / shared resource group instances. Skip the resources you intentionally share with other environments.
2. **Create the GitHub Environment**: Settings → Environments → New environment → name it (e.g. `staging`).
3. **Add the environment secrets** listed above. For `RESOURCE_SUFFIX`, run `openssl rand -hex 3` locally, paste the result, and don't change it afterwards — resource names depend on it staying stable. Skip any secrets you've intentionally placed at repository scope for shared infrastructure.
4. **(Optional) Configure protection rules** on the GitHub Environment: required reviewers, deployment branch restrictions, wait timers.
5. **Run the workflow**: Actions → Deploy Azure Applications → "Run workflow", enter the environment name, fill in the image/app tags, and dispatch.

No YAML changes are required to add a new environment.

### Resources Deployed

- **Main API Function App** (`{prefix}haste{suffix}func`)
- **Titiler API Function App** (`{prefix}hastetitiler{suffix}func`)
- **Queue Processing Function App** (`{prefix}hastequeue{suffix}func`)
- **Static Web App** (`{prefix}haste{suffix}swa`)

### Deployment Process

Executes the `deploy_apps.sh` script with parameters resolved from inputs and repository/environment secrets to deploy all Azure resources and configure application settings.

---

## Other Workflows

These workflows run automatically and require no manual configuration beyond the standard repository setup.

| Workflow | File | Triggers | Purpose |
|----------|------|----------|---------|
| **CodeQL Advanced** | `codeql.yml` | Push and PR to `main`, plus a weekly schedule (Mondays 09:15 UTC) | Static analysis / code scanning for the `actions`, `javascript-typescript`, and `python` languages |
| **Deploy Documentation** | `docs-deploy.yml` | Push to `main`, plus manual dispatch | Builds the Jupyter Book docs and deploys them to GitHub Pages |
| **Secret Scan** | `secret-scan.yml` | Push and PR to `main`, plus manual dispatch | Runs Gitleaks to detect accidentally committed secrets |

> **Note on the Docker build workflow:** the `detect-changes` job uses
> [`dorny/paths-filter`](https://github.com/dorny/paths-filter) for Docker-only
> changes. `hastelib/**` changes are intentionally excluded because
> `hastegeo-publish.yml` builds both final ACR images once with the matching RC
> wheel tag. Manual dispatch always builds the requested image(s).