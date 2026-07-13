# GitHub Actions Workflows Documentation

This directory contains GitHub Actions workflows for the HASTE project, focused on building and pushing Docker images to Azure Container Registry (ACR) using OpenID Connect (OIDC) authentication and semantic versioning.

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

**When**: Automatically triggered when PRs are opened, updated, or synchronized against the `main` branch.

**Default Behavior**:
- **Image Directory**: `all` (builds both images)
- **Tag**: `{TAG_PREFIX}-rc{PR_NUMBER}` (e.g., `1.0.1-rc123`)

#### 2. Manual Workflow Dispatch

```yaml
on:
  workflow_dispatch:
    inputs:
      image_dir: # choice: all, training, imageryprep
      image_tag: # string: custom tag
```

**When**: Manually triggered from the GitHub Actions UI for production releases.

**Parameters**:
- **Image Directory**: Choose from dropdown (`all`, `training`, `imageryprep`)
- **Custom Tag**: Text input for custom tag (default: `test-manual`)

**How to Use**:
1. Go to GitHub Actions tab
2. Select "Build and Push Docker Images" workflow
3. Click "Run workflow"
4. Choose parameters and run

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

> **Note on the Docker build workflow:** the `detect-changes` job uses [`dorny/paths-filter`](https://github.com/dorny/paths-filter) so that a PR only rebuilds the images whose source actually changed (`docker/training/**` or `hastelib/**` for training, `docker/imageryprep/**` for imagery prep). Manual dispatch always builds the requested image(s).