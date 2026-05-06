# Getting Started

This guide will help you get HASTE up and running on your local development environment.

## Prerequisites

- **Python 3.11+** (via Conda)
- **Node.js 18+**
- **Azure Functions Core Tools** v4
- **Conda or Miniconda**
- **GDAL 3.9.2** (installed automatically via conda environment)

## Environment Setup

### 1. Clone the Repository

```bash
git clone https://github.com/microsoft/haste.git
cd haste
```

### 2. Create Conda Environment

The `env.yml` file sets up a `haste_env` conda environment with Python 3.11, GDAL, and all Python dependencies:

```bash
conda env create -f env.yml
conda activate haste_env
```

This installs the `haste` core library in editable mode (`-e hasteutils/`) along with all Azure SDK, geospatial, and ML dependencies.

### 3. Configure Local Settings

Copy the example settings and fill in your values:

```bash
cp local.settings.example.jsonc api/hastefuncapi/local.settings.json
cp local.settings.example.jsonc api/hastefuncqueues/local.settings.json
```

Key settings to configure:

| Setting | Description | Default for local dev |
|---------|-------------|-----------------------|
| `METADATA_STORAGE_TYPE` | Storage backend for metadata | `localfilesystem` |
| `IMAGERY_STORAGE_TYPE` | Storage backend for imagery | `localfilesystem` |
| `ARTIFACT_STORAGE_TYPE` | Storage backend for artifacts | `localfilesystem` |
| `DATA_PATH` | Base path for local data | `c:\temp\haste_data` |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Storage connection | Required for queue/blob |
| `COSMOS_CONNECTION_STRING` | CosmosDB connection | Required for cosmos backend |

For fully local development (no Azure services), set all storage types to `localfilesystem`.

### 4. Start the Azurite Storage Emulator (Optional)

If using Azure Storage queues locally:

```bash
# Using Docker
docker run -p 10000:10000 -p 10001:10001 -p 10002:10002 \
  mcr.microsoft.com/azure-storage/azurite

# Or install globally and run directly
npm install -g azurite
azurite
```

### 5. Start API Services

```bash
cd api/hastefuncapi
func host start
```

In a separate terminal, start queue workers:

```bash
cd api/hastefuncqueues
func host start
```

### 6. Start the UI

```bash
cd ui
npm install
npm run dev
```

The UI will be available at `http://localhost:5173`. You can also use the SWA CLI for a more production-like setup:

```bash
cd ui
swa start --app-devserver-url http://localhost:5173 --config-name local --run 'npm run dev'
```

## Docker Setup (Alternative)

For a containerized setup, see the `docker/` directory:

```bash
cd docker
docker-compose up -d
```

This starts the training service with GPU support. Other services (api, ui, emulators) are defined but commented out by default — uncomment as needed.

## Next Steps

- Review the {doc}`architecture` for system overview
- Explore the {doc}`api-overview` for endpoint details
- Browse the {doc}`api/modules` for API reference
- Check the {doc}`development` guide for coding standards
