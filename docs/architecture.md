# Architecture

HASTE follows a microservices architecture built on Azure cloud services. This page describes how the components fit together.

## High-Level Overview

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

## Components

### REST API — `hastefuncapi`

Python Azure Functions app exposing 28 HTTP endpoints organized around:

- **Projects**: CRUD operations, statistics, dashboard data
- **Image Layers**: Create/delete layers, queue imagery for preprocessing
- **Models**: Training configuration, inference runs, artifact management
- **Labels**: Save/load labeling tool data, label project management
- **Users**: User management, invitations, role-based access
- **Admin**: System configuration, source types, labeling tool settings
- **Model Catalog**: Browse, add, and remove base models

All endpoints use `func.AuthLevel.FUNCTION` authentication.

### Queue Workers — `hastefuncqueues`

Python Azure Functions app with 6 queue-triggered functions for long-running operations:

| Queue | Function | Purpose |
|-------|----------|---------|
| Image queue | `GetProcessImageLayerQueueMessage` | Download, preprocess, and tile satellite imagery |
| Train queue | `GetCreateModelRunQueueMessage` | Execute ML model training via Azure Batch |
| Inference queue | `GetRunInferenceQueueMessage` | Run model inference on imagery |
| Stats queue | `UpdateStatsMessage` | Regenerate project statistics |
| Zip queue | `GetArtifactsZipQueueMessage` | Package model artifacts for download |
| Image poison queue | `ImagePoisonQueueHandler` | Handle failed image processing messages |

### Tile Server — `titilerfuncapi`

A [TiTiler](https://developmentseed.org/titiler/)-based tile server deployed as an Azure Function, providing:

- `/cog/*` — Cloud Optimized GeoTIFF tile endpoints
- `/stac/*` — SpatioTemporal Asset Catalog endpoints
- `/mosaicjson/*` — MosaicJSON mosaic endpoints
- `/tms/*` — TileMatrixSet metadata
- `/healthz` — Health check

### Core Library — `haste` (hasteutils)

Shared Python package (`haste` v0.0.67) installed as an editable package (`-e hasteutils/`). Contains:

- **`haste.core.config`** — Environment-aware configuration (storage types, queue names, paths)
- **`haste.core.models`** — Pydantic data models for projects, users, training, admin, stats, and visualization
- **`haste.core.processors`** — Business logic for imagery, training, inference, labels, stats, artifacts, and uploads
- **`haste.core.data_layer`** — Storage backends: local filesystem, Azure Blob, CosmosDB, Data Lake, PostgreSQL
- **`haste.core.artifact_storage`** — Artifact storage abstraction: local filesystem and Azure Blob
- **`haste.core.runners`** — Task execution: Azure Batch runner for GPU workloads
- **`haste.core.utils`** — Shared utilities: logging, queues, imagery processing, downloads, metadata, TensorBoard parsing
- **`haste.workflows`** — CLI entry points for imagery preparation and artifact zipping

### UI — React Single-Page Application

Built with Vite + React, using:

- **@fluentui/react** for UI components
- **Azure Maps** for geospatial visualization
- **MSAL** for Azure AD authentication
- **Chart.js** for statistics dashboards
- **@turf/turf** for geospatial calculations

Key UI features: project management, image layer configuration, labeling tool, model training/inference management, result visualization, admin settings, and a model catalog.

## Storage Architecture

HASTE supports multiple storage backends, configurable per deployment:

| Storage Type | Use Case | Backend Options |
|-------------|----------|-----------------|
| Metadata | Project/model/user records | Local filesystem, Azure Blob, CosmosDB, Data Lake, PostgreSQL |
| Imagery | Satellite imagery files | Local filesystem, Azure Blob |
| Artifacts | Model weights, predictions | Local filesystem, Azure Blob |
| Queues | Async task messages | Azure Queue Storage |

## Docker Services

The `docker/` directory provides containerized deployments:

| Service | Image | Purpose |
|---------|-------|---------|
| `api` | Azure Functions Python 3.11 | REST API on port 7071 |
| `training` | Azure ML GPU (CUDA 11.8) | Model training with GPU support |
| `imageryprep` | Azure Functions Python 3.11 | Imagery preprocessing scripts |
| `titiler` | developmentseed/titiler | Tile serving on port 8000 |
| `emulators` | Azurite | Local Azure Storage emulator (ports 10000-10002) |
| `ui` | Node.js 20 | Production UI build served on port 5000 |

## CI/CD

- **Azure Pipelines** (`azure-pipelines.yml`): Security scanning (CredScan, vulnerability assessment, PoliCheck, component governance)
- **Docker build script** (`build_and_push_images.sh`): Build and push `hastetraining` and `hasteimageryprep` images to Azure Container Registry
