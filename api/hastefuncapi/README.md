# HASTE Function API

Azure Functions backend for the HASTE application. Provides REST endpoints for managing projects, image layers, ML model training/inference, labeling, user management, and geospatial data access.

---

## Overview

All functions are defined in `function_app.py` as a single Azure Functions app. Authentication is controlled by the `DEVELOPMENT_MODE` environment variable:

- **Development (`DEVELOPMENT_MODE=true`):** Auth level is `ANONYMOUS`; user accounts are auto-created on first login.
- **Production:** Auth level is `FUNCTION`; Azure Static Web Apps client principal headers are used for identity/role checks (required for admin endpoints).

---

## Endpoints

### Projects

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetDashboardData` | Aggregated dashboard stats: project summaries, layer info, model status, and system-wide metrics. |
| GET | `GetProjects` | All projects with aggregated layer and model counts. |
| GET | `GetProjectDetails` | Project, layer, validation, and optional model details. Supports `ETag`/`If-None-Match`; requires `projectId`. |
| PUT | `PutProject` | Create or update a project. Auto-generates `projectId` and `creationDate` if not provided. |
| DELETE | `DeleteProject` | Delete a project by `projectId`. |
| GET | `GenerateProjectStats` | Regenerates project stats from raw data — useful if stats fall out of sync. |

#### Project Detail Caching

`GetProjectDetails` returns `ETag`, `Cache-Control`, and `X-Haste-Cache` headers.
Send `If-None-Match` to receive an empty `304` when the fresh cached representation is
unchanged. Send `Cache-Control: no-cache` after a mutation to force storage refresh and
then compare the ETag.

The response cache is bounded and process-local. It deduplicates concurrent requests but
does not provide coherence across scaled-out Function workers. Performance headers named
`X-Haste-Data-Layer-*` count logical calls, not Azure Storage REST transactions.

### Image Layers

| Method | Route | Description |
|--------|-------|-------------|
| PUT | `PutLayer` | Create or update an image layer. |
| DELETE | `DeleteLayer` | Delete a layer. Requires `projectId` and `imageLayerId`. |
| GET | `GetLayerDetailView` | Detail view for a single image layer. Requires `projectId` and `imageLayerId`. |
| GET | `GetLayerModelsDetails` | Model status and model list for a given layer. Requires `projectId` and `imageLayerId`. |
| GET | `GetLayerLabelingToolData` | Label tool data for a given layer. Requires `projectId` and `imageLayerId`. |
| PUT | `PutLabelsFromLabelTool` | Save labels for a layer from the label tool. |

### File Upload

| Method | Route | Description |
|--------|-------|-------------|
| POST | `UploadFileByChunk` | Upload large geospatial files in chunks. Supports resumable uploads and parallel chunk processing with progress tracking and validation. |

### Model Training & Inference

| Method | Route | Description |
|--------|-------|-------------|
| PUT | `PutRunModelQueueMessage` | Queue a model training run. |
| PUT | `PutCancelModelQueueMessage` | Cancel a queued or running training **or inference** job for a model. |
| PUT | `PutRunInferenceQueueMessage` | Queue an inference run. |
| DELETE | `DeleteModel` | Delete a model. Requires `projectId` and `modelId`. |
| GET | `GetVisualizerResults` | Visualizer data with imagery layers and TiTiler tile URLs with colormaps. Requires `projectId`, `imageLayerId`, and `modelId`. |
| PUT | `PutArtifactsZipQueueMessage` | Queue a job to zip model artifacts for download. |

### Model Catalog

These endpoints use `FUNCTION`-level auth regardless of development mode (intended for system-to-system calls).

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetModelCatalog` | All available base models. Supports filtering by `eventTypes` (comma-separated) and `imagerySource`. |
| PUT | `PutModelCatalog` | Add a HASTE or external model to the catalog for reuse as a base model. |
| DELETE | `DeleteModelCatalog` | Remove a model from the catalog by `baseModelName` or `modelId`. |

### Validation & Assessment

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetBuildingFootprintsGeoJSON` | Random sample of building footprints as a GeoJSON FeatureCollection. `sample` param controls count (1–2000, default 200). |
| GET | `GetBuildingValidation` | Existing building validation labels for a layer (Damaged / NotDamaged / Unknown). |
| PUT | `PutBuildingValidation` | Save (replace) building validation labels for a layer. |
| GET | `GetValidationReport` | Validation accuracy report: confusion matrix, accuracy, precision, recall, F1. Crosses inference results with user-supplied labels. |
| GET | `GetAssessmentReport` | Full damage assessment: precision/recall/AP against labels, plus a finite-population estimate with 95% CI for damaged building count. Supports `threshold` and `minAreaM2` query params. |

### Users & Admin

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetSessionBootstrap` | Trusted current-user, role, settings, and publishing capabilities for one-call application startup. Accepts no caller identity parameters. |
| GET | `GetUsers` | All users. Requires `administrators` role. |
| GET | `GetUserById` | Single user by `userId`. |
| PUT | `PutUser` | Create or update a user. Handles invitations, reinvitations, role assignment, and reactivation. |
| DELETE | `DeleteUser` | Delete a user by `userId` (email). Requires `administrators` role. |
| GET | `GetAdminSettings` | All admin settings. Requires `administrators` role. |
| PUT | `PutAdminSettings` | Update admin settings. Requires `administrators` role. |

#### Session Bootstrap

`GetSessionBootstrap` resolves identity from the SWA client-principal header,
loads current HASTE ACL state, and returns user and publishing configuration in
one response. Stable active sessions are read-only; inactive, pending, and
deleted accounts receive no application roles.

### Published Datasets

`GetPublishedDatasets` returns `ETag`, `Cache-Control`, and `X-Haste-Cache`
headers. Send `If-None-Match` to receive an empty `304` for an unchanged fresh
representation. The bounded process-local cache expires within five seconds,
deduplicates concurrent identical reads, and is invalidated after publishing
mutations.

### Utilities

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetAzureMapsToken` | Short-lived Azure AD token for Azure Maps, obtained via managed identity. |
| OPTIONS | `options/{*path}` | CORS preflight handler — automatically responds to all OPTIONS requests. |

---

## Development Setup

### Prerequisites

Install Azure Functions Core Tools:

```bash
npm install -g azure-functions-core-tools@4 --unsafe-perm true
```

Docs: https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local

### Running Locally

Set environment variables in `local.settings.json`, including `DEVELOPMENT_MODE=true` to bypass authentication.

Launch the app:

```bash
func start
```

Or use the `Launch Functions` VS Code launch configuration.

### Local Debugging

Add a breakpoint in code:

```python
breakpoint()
```

Then use the `Launch Functions` VS Code task. When execution reaches the breakpoint, the terminal drops into a `pdb` prompt with full debugger support.

> **Note:** The VS Code visual breakpoint UI will not work here — the Azure Functions process is not attached to the VS Code Python debugger.
