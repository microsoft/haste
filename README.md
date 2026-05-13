# HASTE

**High-speed Assessment and Satellite Tracking for Emergencies**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE.txt)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://microsoft.github.io/haste)

HASTE is an AI-driven framework for rapid disaster assessment using satellite and remote sensing data. It automates geospatial analysis with machine learning to produce accurate disaster maps, and provides a user-friendly web interface so that non-technical users can generate critical insights alongside disaster experts.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         React UI (Vite)                          │
│  Projects · Labeling Tool · Visualizer · Admin · Model Catalog   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────────────┐
│               Azure Static Web Apps / SWA CLI                    │
└──────┬────────────────────────────────────────────┬─────────────┘
       │ /api/*                                     │ tile requests
┌──────▼──────────────┐                    ┌────────▼─────────────┐
│   hastefuncapi       │                    │   titilerfuncapi     │
│   (28 HTTP routes)   │                    │   (TiTiler/FastAPI)  │
│   Azure Functions    │                    │   COG tile serving   │
└──────┬──────────────┘                    └──────────────────────┘
       │ Queue messages
┌──────▼──────────────┐
│   hastefuncqueues    │
│   (6 queue triggers) │
│   Azure Functions    │
└──────┬──────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│                    haste core library                             │
│  Config · Models · Processors · Data Layers · Runners · Utils    │
└──────┬───────────┬───────────┬───────────┬──────────────────────┘
       │           │           │           │
  ┌────▼───┐  ┌───▼────┐  ┌──▼───┐  ┌───▼──────────┐
  │ Blob   │  │ Cosmos │  │ Data │  │ Azure Batch  │
  │ Storage│  │ DB     │  │ Lake │  │ (GPU pools)  │
  └────────┘  └────────┘  └──────┘  └──────────────┘
```

## Quick Start

The fastest way to run HASTE locally is with Docker Compose, which starts the full stack — API, queue workers, tile server, storage emulator, and UI — with no Azure subscription required.

**Prerequisites:** [Docker](https://www.docker.com/products/docker-desktop) and [Docker Compose](https://docs.docker.com/compose/install/)

```bash
git clone https://github.com/microsoft/haste.git
cd haste
docker-compose -f docker/docker-compose.yml up
```

| Service | URL |
|---------|-----|
| UI | http://localhost:4280 |
| REST API | http://localhost:7071 |
| TiTiler tile server | http://localhost:8080 |
| Azurite storage emulator | http://localhost:10000 |

> **Note:** The Docker Compose stack is for local development and evaluation only. It uses development defaults (in-memory storage emulator, disabled auth, wildcard CORS) that are not suitable for production. See [docs/deployment.md](docs/deployment.md) for production deployment.

> For Azure-connected development and production deployment, see [Project Setup](#project-setup) below and the [full documentation](https://microsoft.github.io/haste).

## Documentation

Full documentation is published at **[https://microsoft.github.io/haste](https://microsoft.github.io/haste)** and covers:

- [Getting Started](https://microsoft.github.io/haste/getting-started.html)
- [Architecture](https://microsoft.github.io/haste/architecture.html)
- [API Reference](https://microsoft.github.io/haste/api/modules.html)
- [Deployment Guide](https://microsoft.github.io/haste/deployment.html)
- [Secure Configuration Guidance](https://microsoft.github.io/haste/security-configuration.html)

Source for the docs lives in [`docs/`](docs/) and is built with [Jupyter Book](https://jupyterbook.org/).

## Components

| Component | Technology | Description |
|-----------|-----------|-------------|
| **UI** | React + Vite | Single-page app for project management, labeling, and visualization |
| **REST API** (`hastefuncapi`) | Python Azure Functions | 28 HTTP endpoints for CRUD operations |
| **Queue Workers** (`hastefuncqueues`) | Python Azure Functions | 6 queue-triggered functions for async processing |
| **Tile Server** (`titilerfuncapi`) | TiTiler + FastAPI | Cloud Optimized GeoTIFF tile serving |
| **Core Library** (`haste`) | Python package | Shared models, processors, data layers, and utilities |

## Project Setup

### Prerequisites for local development

- [Node.js](https://nodejs.org/en/download/) (LTS version) — or use `nvm` (see [Additional Developer Notes](#additional-developer-notes))
- [Azure Functions Core Tools v4](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local?tabs=windows%2Cisolated-process%2Cnode-v4%2Cpython-v2%2Chttp-trigger%2Ccontainer-apps&pivots=programming-language-python#install-the-azure-functions-core-tools)
- [Azure Static Web Apps CLI](https://learn.microsoft.com/en-us/azure/static-web-apps/static-web-apps-cli-install)
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- [TiTiler](https://github.com/developmentseed/titiler.git)
- [Python 3.11+](https://www.python.org/downloads/)
- [Docker](https://www.docker.com/products/docker-desktop) and [Docker Compose](https://docs.docker.com/compose/install/)
- [Terraform](https://learn.hashicorp.com/tutorials/terraform/install-cli)
- [PowerShell](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-linux?view=powershell-7.4) (WSL only)
- [Conda](https://docs.anaconda.com/miniconda/)

---

### UI setup

#### Install dependencies

```bash
cd ui
npm install
```

#### Azure Static Web Apps emulator setup

See the [Azure Static Web Apps local development guide](https://learn.microsoft.com/en-us/azure/static-web-apps/local-development) for full details.

1. Install the SWA CLI:
```bash
npm install --global @azure/static-web-apps-cli@latest
```

2. Select **Launch React** from the VSCode debugger. This runs the app in hot-reload mode through the emulator.

3. Go to http://localhost:4280. You will be presented with an auth form to set up a mock AAD user. Add `administrators` or `contributors` to the user's roles.

#### Azure Static Web Apps deployment

```bash
cd ui
swa build
swa deploy --app-location ./dist --app-name <YOUR_STATIC_WEB_APP_NAME> --tenant-id <YOUR_TENANT_ID> --subscription-id <YOUR_SUBSCRIPTION_ID> --env preview --deployment-token <YOUR_DEPLOYMENT_TOKEN>
```

See the [Azure Static Web Apps authentication docs](https://learn.microsoft.com/en-us/azure/static-web-apps/configuration#authentication) for configuring authentication.

---

### API backend setup

Switch to the API directory:

```bash
cd api/hastefuncapi
```

#### Install dependencies

```bash
npm install -g azure-functions-core-tools@4 --unsafe-perm true
```

#### Download and install GDAL for local development

> This step is only necessary if you are **not** using conda.

Download GDAL wheels from the appropriate source for your platform:

- **Windows** (local development): [cgohlke/geospatial-wheels](https://github.com/cgohlke/geospatial-wheels/releases/download/v2024.9.22/GDAL-3.9.2-cp311-cp311-win_amd64.whl)
- **Linux** (Azure deployment): [girder/large_image_wheels](https://github.com/girder/large_image_wheels/raw/wheelhouse/GDAL-3.9.2-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl#sha256=0df4da716949c7a6d28ac0be1471da540ef82aaf6c235a3864597eaabceeef21)

```bash
curl -LJO https://github.com/girder/large_image_wheels/raw/wheelhouse/GDAL-3.6.4-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl#sha256=a05e038549c009e3ce8282af2ad2d80c3671eeccf673d5b001cf326f84986d2b
pip install GDAL-3.6.4-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
```

#### Install the haste core library in editable mode

The core library is a standalone Python package shared by the API backend and Azure Batch compute backends. Install in editable mode for hot-reload during local development.

```bash
# First-time setup:
conda env create -f env.yml

# Updating an existing environment:
# conda env update -f env.yml

conda activate haste_env
pip install -e hastelib/
```

> **VSCode tip:** If Ctrl+Click navigation stops working or `haste.core` modules show "module not found", ensure the `haste_env` interpreter is selected and restart the language server.

#### Setup for local development

Create a `local.settings.json` file in `api/hastefuncapi/` with the following contents. See [local.settings.example.jsonc](local.settings.example.jsonc) for a full description of all configuration variables.

```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsFeatureFlags": "EnableWorkerIndexing",
    "METADATA_STORAGE_TYPE": "blob",
    "IMAGERY_STORAGE_TYPE": "blob",
    "RUNNER_TYPE": "azure_batch",
    "AzureWebJobsStorage": "<Azurite connection string>",
    "AZURE_BATCH_ACCOUNT_KEY": "<from Azure portal>"
  },
  "Host": {
    "LocalHttpPort": 7071,
    "CORS": "http://localhost:5173,http://localhost:4280"
  }
}
```

Use explicit localhost origins for local development and avoid wildcard CORS. Production environments should allow only trusted UI origins. See the [Azure Functions local development docs](https://learn.microsoft.com/en-us/azure/azure-functions/functions-develop-local) for more information.

To test endpoints that run batch jobs, update `AzureWebJobsStorage` to point to the `hasteimagedevstg` account and add `BLOB_ACCOUNT_URL` and `BLOB_ACCOUNT_NAME` keys.

#### Deploying Azure Functions

Build the standalone haste core package first:

```bash
cd hastelib/
conda activate haste_build
hatch build -t wheel
```

The `hatch build` command automatically:
- Increments the version in `hastelib/src/haste_geo/__about__.py`
- Builds a wheel and copies it to the function app folders
- Updates the package version in all `requirements.txt` and `env.yml` files

Then deploy the function apps:

```bash
az login --tenant <YOUR_TENANT_ID>
az account set --subscription <YOUR_SUBSCRIPTION_ID>
az functionapp create --flexconsumption-location westus2 --runtime python --runtime-version 3.11 --functions-version 4 --name <YOUR_FUNCTION_APP_NAME> --os-type linux -g <YOUR_RESOURCE_GROUP> -s <YOUR_STORAGE_ACCOUNT>

# Deploy or update an existing function app
func azure functionapp publish <YOUR_FUNCTION_APP_NAME> --subscription <YOUR_SUBSCRIPTION_ID> --tenant <YOUR_TENANT_ID> --resource-group <YOUR_RESOURCE_GROUP>
```

See the [Flex Consumption deployment guide](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to?tabs=azure-cli%2Cvs-code-publish&pivots=programming-language-python) for more options.

#### Queue and storage setup locally

```bash
npm install -g azurite
azurite --silent --location ./data --debug ./data/debug.log
```

See the [Azure Storage Emulator docs](https://docs.microsoft.com/en-us/azure/storage/common/storage-use-azurite?tabs=npm%2Cqueue-storage) for more options, including [RabbitMQ](https://www.rabbitmq.com/download.html) as an alternative queue backend.

> **Note:** `azurite` is not a project dependency — install it globally with `npm install -g azurite`. It is used only for local development and is never deployed.

---

### TiTiler setup

```bash
git clone https://github.com/developmentseed/titiler.git
cd titiler/deployment/azure
az login --tenant <YOUR_TENANT_ID>
az account set --subscription <YOUR_SUBSCRIPTION_ID>
az functionapp create --consumption-plan-location westus2 --runtime python --runtime-version 3.11 --functions-version 4 --name <YOUR_TITILER_FUNCTION_NAME> --os-type linux -g <YOUR_RESOURCE_GROUP> -s <YOUR_STORAGE_ACCOUNT>
func azure functionapp publish <YOUR_TITILER_FUNCTION_NAME> --python
```

---

### Testing batch jobs locally

Mount the `haste` package in hot-reload mode by adding this volume to your `docker run` command:

```bash
-v "`pwd`/hastelib/src/haste_geo":/usr/local/lib/python3.11/site-packages/haste
```

#### Imagery prep

1. Build the required Docker image:
```bash
./build_and_push_images.sh --help
```

2. Create an `imageryprep_config.yaml` file in `localtmp/imagerypreptmp/`:

```yaml
project_id: "123-456"
image_layer_id: "789-111"
source_type: "maxar"
fine_tune: False
pre_event_imagery_urls:
  - https://maxar-opendata.s3.amazonaws.com/events/Maui-Hawaii-fires-Aug-23/ard/04/122000330002/2023-08-12/10300100EB15FF00-visual.tif
post_event_imagery_urls:
  - https://maxar-opendata.s3.amazonaws.com/events/Maui-Hawaii-fires-Aug-23/ard/04/122000330002/2023-08-12/10300100EB15FF00-visual.tif
```

3. Start a Docker container with the necessary mounts:

```bash
docker run -it \
  -v "`pwd`/localtmp/prepare_imagery":/wd \
  -v "`pwd`/hastelib/src/haste_geo":/usr/local/lib/python3.11/site-packages/haste \
  -e WORKDIR=/wd \
  --entrypoint bash \
  ${CONTAINER_REGISTRY}.azurecr.io/hasteimageryprep:${tag}
```

4. Run the imagery prep script:

```bash
prepare-imagery --config /wd/imageryprep_config.json
```

Outputs are written to `localtmp/prepare_imagery/outputs/`. Changes to `hastelib/src/haste_geo/workflows/prepare_imagery.py` are reflected immediately via the volume mount.

#### Training

1. Build the training image.

2. Set up inputs in `localtmp/training/`.

3. Run the Docker container:

```bash
docker run --gpus all -it --shm-size=32g \
  -v "`pwd`/localtmp/training":/wd \
  -v "`pwd`/hastelib/src/haste_geo":/usr/local/lib/python3.11/site-packages/haste \
  -v "`pwd`/docker/training:/app" \
  -e WORKDIR=/wd \
  --entrypoint bash \
  ${CONTAINER_REGISTRY}.azurecr.io/hastetraining:${tag}
```

Inside the container:

```bash
export GDAL_TRANSLATE_PARAMS='BIGTIFF=YES NUM_THREADS=ALL_CPUS COMPRESS=DEFLATE PREDICTOR=2'
export AZ_BATCH_TASK_WORKING_DIR="/wd"
conda init && source ~/.bashrc
conda activate bda
source scripts/set_dirs.sh $AZ_BATCH_TASK_WORKING_DIR/inputs/<config_file>
python run_workflow.py --step training --config ${AZ_BATCH_TASK_WORKING_DIR}/inputs/<config_file>
```

---

### Additional developer notes

#### Managing Node versions with nvm

`nvm` is the recommended way to install and manage Node.js versions. See [Steps to install nvm on WSL](https://learn.microsoft.com/en-us/windows/dev-environment/javascript/nodejs-on-wsl#install-nvm-nodejs-and-npm).

`nvm` can break VSCode tasks because it adds shell variables to login shells but not to the non-login shells VSCode uses for tasks. Fix this by adding the following to `~/.bash_profile` and restarting VSCode:

```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
```

#### Setting up the conda environment on WSL

```bash
conda env create -f env.yml
```

#### Cleaning up `__pycache__` and `.pyc` files

```bash
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -name "*.pyc" -delete
```

#### Other local emulators

See the [Azure Cosmos DB emulator docs](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-develop-emulator?tabs=docker-linux%2Ccsharp&pivots=api-nosql) for running Cosmos DB locally.

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for coding standards, the pull request process, and the Contributor License Agreement requirement.

- [Open an issue](../../issues) to report a bug or request a feature
- [Start a discussion](../../discussions) for questions or ideas
- [Read the security policy](SECURITY.md) before reporting vulnerabilities

## License

This project is licensed under the MIT License — see [LICENSE.txt](LICENSE.txt) for details.

## Third-Party Software

This project includes third-party components. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for details.
