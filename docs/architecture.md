# Architecture

HASTE follows a microservices architecture built on Azure cloud services. This page describes how the components fit together.

## High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                            React UI (Vite)                            │
│  Projects · Labeling · Interactive Labeler · Building Validation ·    │
│  Visualizer · Admin · Model Catalog · Help Docs                       │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ HTTP
┌────────────────────────────────▼─────────────────────────────────────┐
│   Azure Static Web Apps + API Management (prod)                       │
│   SWA CLI + nginx api-proxy (local)                                   │
└──────┬──────────────────────────────────────────────┬────────────────┘
       │ /api/*                                       │ tile requests
┌──────▼──────────────┐                      ┌────────▼─────────────┐
│   hastefuncapi       │                      │   titilerfuncapi     │
│   (41 HTTP routes)   │                      │   (TiTiler / FastAPI)│
│   Azure Functions    │                      │   COG tile serving   │
└──────┬──────────────┘                      └──────────────────────┘
       │ Queue messages
┌──────▼──────────────────────┐
│   hastefuncqueues            │
│   (6 queue workers + poison) │
│   Azure Functions            │
└──────┬──────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────────┐
│                        hastegeo core library                          │
│  Config · Models · Processors · Data Layer · Artifact Storage ·      │
│  Runners · Utils · Workflows                                          │
└──────┬───────────┬───────────┬───────────┬───────────┬──────────────┘
       │           │           │           │           │
  ┌────▼───┐  ┌───▼────┐  ┌──▼───┐  ┌────▼─────┐  ┌───▼──────────┐
  │ Blob   │  │ Cosmos │  │ Data │  │ Postgres │  │ Azure Batch  │
  │ Storage│  │ DB     │  │ Lake │  │          │  │ (GPU pools)  │
  └────────┘  └────────┘  └──────┘  └──────────┘  └──────────────┘
```

## Components

### REST API — `hastefuncapi`

Python Azure Functions app exposing **41 HTTP endpoints** organized around:

- **Projects**: list/detail, create/update, delete, dashboard data, statistics generation
- **Image Layers**: create/update, delete, detail view, labeling-tool data
- **Models**: delete, artifact retrieval, and queue-message endpoints to run training, inference, embedding, cancellation, and artifact zipping
- **Labels & Validation**: save/load labeling-tool data, interactive labels, building validation, and validation/assessment reports
- **Building features**: building footprints and building embeddings as GeoJSON, and prediction upload
- **Users & Admin**: user management, admin settings, and role-based access
- **Model Catalog**: browse, add, and remove base models
- **Infrastructure**: chunked file upload, Azure Maps token, and CORS preflight

Authentication is **environment-dependent**. The shared `AUTH_LEVEL` resolves to
`func.AuthLevel.ANONYMOUS` when `DEVELOPMENT_MODE=true` (local/dev) and
`func.AuthLevel.FUNCTION` otherwise (production, where API Management fronts the app and
injects the Function host key). Admin routes additionally enforce an `administrators` role
from the SWA-provided `x-ms-client-principal` header, and the Model Catalog routes are
always `FUNCTION`. Responses are shaped per endpoint — there is no global response
envelope.

### Queue Workers — `hastefuncqueues`

Python Azure Functions app with **6 queue-triggered workers plus a poison-queue handler**
for long-running operations:

| Queue | Function | Purpose |
|-------|----------|---------|
| `image-layers-queue` | `GetProcessImageLayerQueueMessage` | Download, preprocess, and tile satellite imagery |
| `train-queue` | `GetCreateModelRunQueueMessage` | Execute ML model training via the configured runner |
| `embedding-queue` | `GetRunEmbeddingQueueMessage` | Run the building-embedding job that powers the Interactive Labeler |
| `inference-queue` | `GetRunInferenceQueueMessage` | Run model inference on imagery |
| `stats-queue` | `UpdateStatsMessage` | Regenerate project statistics |
| `zip-queue` | `GetArtifactsZipQueueMessage` | Package model artifacts for download |
| `image-layers-queue-poison` | `ImagePoisonQueueHandler` | Mark image layers `FAILED` when image processing exhausts retries |

### Tile Server — `titilerfuncapi`

A [TiTiler](https://developmentseed.org/titiler/) `0.21.1` tile server (FastAPI, run as an
Azure Function via an ASGI wrapper), providing:

- `/cog/*` — Cloud Optimized GeoTIFF tile endpoints
- `/stac/*` — SpatioTemporal Asset Catalog endpoints
- `/mosaicjson/*` — MosaicJSON mosaic endpoints
- `/tms/*` — TileMatrixSet metadata
- `/healthz` — health check
- `/` — HTML landing page

The `/cog`, `/stac`, and `/mosaicjson` routers are individually toggleable via settings.

### Core Library — `hastegeo`

Shared Python package **`hastegeo` (v1.0.25)**, with source under `hastelib/src/hastegeo`.
The Function Apps install it from a blob-hosted wheel (`hastegeo-…-py3-none-any.whl`); local
development installs it editable with `-e hastelib/`. It contains:

- **`hastegeo.core.config`** — environment-aware `Config` plus the `StorageType` and `ArtifactTypes` enums
- **`hastegeo.core.models`** — Pydantic models for projects, users, training, admin, stats, uploader, and visualizer
- **`hastegeo.core.processors`** — business logic for imagery, training, inference, embedding, labels, stats, artifacts, metadata, and uploads
- **`hastegeo.core.data_layer`** — metadata backends (local filesystem, Azure Blob, Cosmos DB, Data Lake, PostgreSQL) behind a `UnifiedDataLayer` dispatcher
- **`hastegeo.core.artifact_storage`** — artifact backends (local filesystem, Azure Blob) behind a `UnifiedArtifactStorage` dispatcher
- **`hastegeo.core.runners`** — task execution via `LocalRunner` (Docker) and `AzureBatchRunner` (GPU pools), behind a `UnifiedRunner` dispatcher
- **`hastegeo.core.utils`** — shared utilities: logging, queues, downloads, imagery, footprints, AOI, assessment, GDAL security, URL allow-listing, TensorBoard parsing, and metadata
- **`hastegeo.workflows`** — CLI entry points for imagery preparation (`prepare-imagery`), artifact zipping (`zip-artifacts`), and building embedding

### UI — React Single-Page Application

Built with Vite + React 18 (React Router), using:

- **@fluentui/react** for UI components
- **Azure Maps** (Drawing Tools) for geospatial visualization
- **MSAL** for Entra ID authentication
- **Chart.js** for statistics dashboards
- **PMTiles** and **GeoTIFF** for tile and raster handling

Key UI features: home dashboard, project management, image-layer configuration, the
labeling tool, the model-assisted Interactive Labeler, building validation, result
visualization, admin settings (users, source types, labeling-tool configuration), the model
catalog, and in-app help documentation.

## Storage Architecture

HASTE supports multiple storage backends, configurable per deployment:

| Storage Type | Use Case | Backend Options |
|-------------|----------|-----------------|
| Metadata | Project/model/user records | Local filesystem, Azure Blob, Cosmos DB, Data Lake, PostgreSQL |
| Artifacts | Model weights, predictions, labels | Local filesystem, Azure Blob |
| Imagery | Satellite imagery files | Local filesystem, Azure Blob |
| Queues | Async task messages | Azure Queue Storage |

## Docker Services

The `docker/docker-compose.yml` stack brings up the full platform locally:

| Service | Image / Build | Port | Purpose |
|---------|---------------|------|---------|
| `azurite` | build (`docker/emulators`) | 10000–10002 | Azure Storage emulator (blob, queue, table) |
| `data-init` | build (`docker/data-init`) | — | One-shot: seeds Azurite with defaults, then exits |
| `api-proxy` | nginx | 7071 | CORS reverse proxy in front of the API and tile server |
| `titiler` | build (`docker/titiler`) | 8000 | COG tile server |
| `hastefuncapi` | build (`api/hastefuncapi`) | via proxy | REST API host |
| `hastefuncqueues` | build (`api/hastefuncqueues`) | internal | Queue workers; spawns training/imagery jobs via the LocalRunner |
| `ui` | build (`ui/`) | 4280 | Vite-served React UI (SWA CLI) |
| `training_image` | build (`docker/training`) | — | Build-only image the LocalRunner runs for training |
| `imageryprep_image` | build (`docker/imageryprep`) | — | Build-only image the LocalRunner runs for imagery prep |
| `training` | build (`docker/training`) | — | Optional standalone training service (`--profile standalone`) |

## CI/CD

GitHub Actions workflows under `.github/workflows/`:

- **Security scanning** — CodeQL (`codeql.yml`) and Gitleaks secret scanning (`secret-scan.yml`), plus GitHub-native Dependabot for dependency alerts
- **Image build** — `docker-build-and-push.yml` (and the `build_and_push_images.sh` helper) build and push the `hastetraining` and `hasteimageryprep` images to Azure Container Registry
- **App deploy** — `deploy-apps.yml` publishes the Function Apps; the one-step `azd up` flow provisions infrastructure and deploys everything (see the [Deployment Guide](deployment.md))
- **Docs** — `docs-deploy.yml` builds this Jupyter Book and publishes it to GitHub Pages
