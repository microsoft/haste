# Deployment Guide

This guide covers deploying HASTE to various environments.

## Azure Deployment

### Prerequisites

- Azure subscription
- Azure CLI installed and configured
- Docker (for containerized deployments)

### Function Apps

The API is deployed as Azure Function Apps:

```bash
# Create resource group
az group create --name haste-rg --location eastus

# Create function app
az functionapp create \
  --resource-group haste-rg \
  --consumption-plan-location eastus \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --name haste-api \
  --storage-account hastestorage
```

### Environment Variables

Configure the following environment variables:

```bash
az functionapp config appsettings set \
  --name haste-api \
  --resource-group haste-rg \
  --settings \
    AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=..." \
    AZURE_COSMOSDB_CONNECTION_STRING="AccountEndpoint=..." \
    IMAGERY_API_KEY="your-api-key"  # pragma: allowlist secret
```

### Static Web App (UI)

Deploy the React UI as an Azure Static Web App:

```bash
# Create static web app
az staticwebapp create \
  --name haste-ui \
  --resource-group haste-rg \
  --source https://github.com/microsoft/haste \
  --branch main \
  --app-location "/ui" \
  --api-location "/api"
```

## Local Development

### Docker Compose

Use Docker Compose for local development:

```bash
cd docker
docker-compose up -d
```

The `docker/docker-compose.yml` defines the following services:

| Service | Base Image | Port | Description |
|---------|-----------|------|-------------|
| `training` | Azure ML GPU (CUDA 11.8) | — | Model training with GPU support (20GB shared memory) |
| `api` | Azure Functions Python 3.11 | 7071 | REST API (commented out by default) |
| `ui` | Node.js 20 | 5000 | Production UI build (commented out by default) |
| `emulators` | Azurite | 10000-10002 | Azure Storage emulator (commented out by default) |

Uncomment the services you need in `docker-compose.yml`. The training service mounts `../data/training` for data access.

### Manual Setup

For manual local setup:

1. **Start API services**:

   ```bash
   cd api/hastefuncapi
   func host start
   ```

2. **Start queue processing**:

   ```bash
   cd api/hastefuncqueues
   func host start
   ```

3. **Start UI**:

   ```bash
   cd ui
   npm install
   npm run dev
   ```

## Production Considerations

### Security

For production deployments, follow the [Secure Configuration Guidance](security-configuration.md) — it covers identity and authentication setup, secrets management with managed identity and Key Vault, CORS and HTTP security headers, container hardening, logging and monitoring, and known limitations with operational mitigations. The guide also includes a pre-production checklist.

### Monitoring

- **Enable Application Insights** for monitoring and logging
- **Set up alerts** for critical failures
- **Monitor resource usage** and scale accordingly

### Backup and Recovery

- **Regular backups** of CosmosDB data
- **Blob storage redundancy** for imagery data
- **Disaster recovery plan** for critical systems

## CI/CD Pipeline

### Azure Pipelines

The project uses Azure Pipelines (`azure-pipelines.yml`) for security and compliance scanning on pushes to `master`:

- **CredScan** — Credential scanning
- **VulnerabilityAssessment** — Security vulnerability detection
- **PoliCheck** — Content policy checking
- **ComponentGovernanceComponentDetection** — Dependency scanning (High alert level)

### Docker Image Build & Push

The `build_and_push_images.sh` script builds and pushes Docker images to Azure Container Registry:

```bash
# Build and push training image
./build_and_push_images.sh -t latest -i training

# Build and push imagery prep image
./build_and_push_images.sh -t latest -i imageryprep

# Build and push all images
./build_and_push_images.sh -t v1.0 -i all
```

Images are pushed to your ACR as `hastetraining` and `hasteimageryprep`. Set `ACR_NAME` in `build_and_push_images.sh` to your registry name before running.

## Troubleshooting

### Common Issues

**Function App Cold Start**
: Functions may have slow initial response. Consider using Premium plans for production.

**Storage Connection Issues**
: Verify connection strings and ensure storage account is accessible.

**CORS Errors**
: Configure CORS settings in Function App to allow UI domain.

**Memory Issues**
: Large imagery processing may require Premium or Dedicated plans.

### Logs and Diagnostics

- **Application Insights** for detailed telemetry
- **Function App logs** via Azure Portal or CLI
- **Storage diagnostics** for blob access issues
