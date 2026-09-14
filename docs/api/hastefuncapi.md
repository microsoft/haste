# HASTE Function API

Azure Functions backend for the HASTE application. Provides REST endpoints for managing projects, image layers, ML model training/inference, labeling, user management, and geospatial data access.

**Contents:** [Overview](#overview) - [Endpoints](#endpoints) -
[Common prediction results](#common-prediction-results) -
[Development setup](#development-setup) - [Generated API docs](#auto-generated-api-docs)

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
| GET | `GetProjectDetails` | Full project details including image layers, models, and processing status. Requires `projectId`. |
| PUT | `PutProject` | Create or update a project. Auto-generates `projectId` and `creationDate` if not provided. |
| DELETE | `DeleteProject` | Delete a project by `projectId`. |
| GET | `GenerateProjectStats` | Regenerates project stats from raw data — useful if stats fall out of sync. |

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
| GET | `GetVisualizerResults` | Shared vector-first results for standard inference and interactive labeling, including imagery and protected artifact URLs. Requires `projectId`, `imageLayerId`, and `modelId`. |
| GET | `GetModelArtifact` | Stream protected model/layer artifacts, including `gpkg`, `prediction_attrs`, and `footprint_pmtiles`. |
| PUT | `PutBuildingPredictions` | Replace interactive predictions and eagerly publish their GeoPackage and matching results sidecar; an empty list clears predictions. |
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
| GET | `GetUsers` | All users. Requires `administrators` role. |
| GET | `GetUserById` | Single user by `userId`. |
| PUT | `PutUser` | Create or update a user. Handles invitations, reinvitations, role assignment, and reactivation. |
| DELETE | `DeleteUser` | Delete a user by `userId` (email). Requires `administrators` role. |
| GET | `GetAdminSettings` | All admin settings. Requires `administrators` role. |
| PUT | `PutAdminSettings` | Update admin settings. Requires `administrators` role. |

### Utilities

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetAzureMapsToken` | Short-lived Azure AD token for Azure Maps, obtained via managed identity. |
| OPTIONS | `options/{*path}` | CORS preflight handler — automatically responds to all OPTIONS requests. |

---

## Common Prediction Results

These routes use the authentication described in [Overview](#overview), not
a separate anonymous artifact service. `projectId` and `imageLayerId` are GUID
strings; `modelId` is a one-to-eight-digit string. A supplied model and image
layer must belong together.

### Create interactive predictions

`PUT /api/PutBuildingPredictions` accepts a complete replacement:

```json
{
  "projectId": "11111111-1111-4111-8111-111111111111",
  "imageLayerId": "22222222-2222-4222-8222-222222222222",
  "modelId": "5557",
  "predictions": [
    {"id": 0, "damaged": 1, "unknown": 0.0},
    {"id": 1, "damaged": 0, "unknown": 0.0}
  ]
}
```

`id` is the zero-based cached footprint row, not a GeoPackage FID. IDs must be
unique and cover the complete footprint set; `damaged` is integer 0 or 1,
`unknown` is a finite fraction between 0 and 1, and optional `overtureId` must
match the source row. `predictions: []` explicitly clears results.

HTTP 200 with JSON means the new generation was published, including its
matching attribute sidecar. Neither HTTP 409 nor an error response means the
predictions were saved. Standard inference creates the same sidecar inside its
existing inference job; no separate preparation request is needed.

### Read results and artifacts

`GET /api/GetVisualizerResults?projectId=...&imageLayerId=...&modelId=...`
returns the existing imagery metadata and these common fields:

| Field | Type | Meaning |
|---|---|---|
| `flavor` | `"inference"` or `"embedding"` | Producer capability, not a heuristic based on score values |
| `supportsThreshold` | boolean | Whether the model has continuous inference scores |
| `defaultThreshold`, `defaultUnknownThreshold` | number | Producer classification defaults, both zero |
| `buildingCount` | integer or null | Preserved prediction count, including explicit zero after clear |
| `predictionRevision` | string or null | Current raw-generation identity |
| `footprintTilesUrl`, `predictionAttrsUrl`, `gpkgUrl` | string or null | API-relative artifact URLs |
| `predictionsReady`, `predictionsReadiness` | boolean, object | Render readiness and its reason/detail |
| `rawPredictionsReady` | boolean | Raw-output availability, separate from renderability |

Embedding results do not fabricate prediction-raster URLs. Opening results is
read-only: it does not generate artifacts, enqueue preparation, or start backfill.
Legacy GeoPackages remain downloadable when the new sidecar is absent.

`GET /api/GetModelArtifact` accepts `projectId`, `kind`, and the artifact owner.
Model-scoped kinds require `modelId`; `footprint_pmtiles` accepts `imageLayerId`
without a model. The existing `sidecar` kind means embedding feature vectors;
`prediction_attrs` means JSON result attributes. Use the returned
`predictionRevision` query parameter for a generation-pinned result request.
An obsolete revision is rejected rather than returning different bytes under
an old cache identity. `version=0` explicitly selects raw GeoPackage output.

| Status | Meaning |
|---|---|
| 200 / 206 | Result JSON or artifact content, including supported range responses |
| 400 | Malformed identifiers, owner mismatch, or invalid prediction rows |
| 404 | Missing model, layer, or artifact |
| 409 | Superseded prediction generation or conflicting publication |
| 500 | Unexpected storage, generation, or publication failure |

See [the shared-results specification](../../spec/features/common-prediction-results/README.md)
for the sidecar schema, generation lifecycle, and deployment requirements.

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

## Auto-generated API Docs

```{eval-rst}
.. azure-function-module:: function_app
   :members:
   :undoc-members:
   :show-inheritance:
```
