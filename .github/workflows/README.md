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
      - development
```

**When**: Automatically triggered when PRs are opened, updated, or synchronized against the `development` branch.

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
IMAGE_TAG: ${{ github.event.inputs.image_tag || format('{0}-RC-{1}', vars.TAG_PREFIX, github.event.number) }}
```

**Logic**:
- **Manual dispatch**: Uses custom input tag
- **PR to development**: Uses `{TAG_PREFIX}-rc{PR_NUMBER}` format

#### Tag Examples

| Trigger Type | Input | Generated Tag | Example |
|--------------|-------|---------------|---------|
| Manual Dispatch | Custom tag: `v2.0.0` | `v2.0.0` | `hastetraining:v2.0.0` |
| Manual Dispatch | Default | `test-manual` | `hastetraining:test-manual` |
| PR #123 to development | N/A | `1.0.1-rc123` | `hastetraining:1.0.1-rc123` |

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

Create a PR against the `development` branch.

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
- Verify PR is against the `development` branch
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

The `deploy-apps.yml` workflow deploys the HASTE application suite to Azure, including Function Apps, Static Web Apps, and configures the necessary cloud infrastructure.

### Trigger

Manual trigger only using `workflow_dispatch` from the GitHub Actions interface.

### Input Parameters

| Parameter | Description | Required | Default | Type |
|-----------|-------------|----------|---------|------|
| `resource_prefix` | Resource naming prefix for all Azure resources | Yes | - | string |
| `location` | Azure region for deployment | Yes | `eastus` | string |

**Note**: The random suffix is automatically generated using `openssl rand -hex 3` to ensure resource name uniqueness.

### Authentication

Uses the same Azure OIDC authentication as the Docker workflow:

| Secret | Description |
|--------|-------------|
| `AZURE_CLIENT_ID` | Service principal client ID |
| `AZURE_TENANT_ID` | Azure Active Directory tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Target Azure subscription ID |

### Resources Deployed

- **Main API Function App** (`{prefix}haste{suffix}func`)
- **Titiler API Function App** (`{prefix}hastetitiler{suffix}func`)
- **Queue Processing Function App** (`{prefix}hastequeue{suffix}func`)
- **Static Web App** (`{prefix}haste{suffix}swa`)

### Deployment Process

Executes the `deploy_apps.sh` script with the provided parameters to deploy all Azure resources and configure application settings.