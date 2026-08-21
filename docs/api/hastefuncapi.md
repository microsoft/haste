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
| PUT | `PutRunEmbeddingQueueMessage` | Queue a building-embedding job for the building labeling workflow. Creates a `modelType="embedding"` model; needs no labels, only the layer's imagery and cached footprints. |
| DELETE | `DeleteModel` | Delete a model. Requires `projectId` and `modelId`. |
| GET | `GetVisualizerResults` | Visualizer data with imagery layers and TiTiler tile URLs with colormaps. Requires `projectId`, `imageLayerId`, and `modelId`. |
| PUT | `PutArtifactsZipQueueMessage` | Queue a job to zip model artifacts for download. |
| GET | `GetModelArtifact` | Stream a model artifact (or an image layer's footprint tiles) through the function app instead of a direct blob SAS URL, honoring HTTP `Range`. See [Model artifacts](#model-artifacts). |

### Building Labeling (Interactive Labeler)

The building labeling workflow trains a small model **in the browser** from
building embeddings, so these endpoints move whole-layer data rather than
per-request samples.

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetBuildingEmbeddingsGeoJSON` | Full building-embeddings GeoJSON (footprints plus `f_*` feature columns, one row per footprint in row-index order). Unlike `GetBuildingFootprintsGeoJSON` this does **not** sample. Requires `projectId` and `modelId`. |
| GET | `GetInteractiveLabels` | The model-scoped labels of the interactive labeler. Separate store from the layer-scoped Building Validation labels. Requires `projectId` and `modelId`. Returns `{"labels": {...}}`. |
| PUT | `PutInteractiveLabels` | Save (replace) the interactive labeler's labels. Body: `{ projectId, imageLayerId, modelId, labels }`. |
| PUT | `PutBuildingPredictions` | Persist the in-browser model's per-building predictions as a GeoPackage and point the embedding model's `gpkgUrl` at it. See below. |

#### `PUT PutBuildingPredictions`

Joins the browser's `damaged` (0/1) calls onto the layer's cached building
footprints **by row index** and writes a predictions GeoPackage with the schema
the reports expect (`id`, `damaged`, `damage_pct_0m`, `unknown_pct`, `area`).

**Request:**

```json
{
  "projectId": "string — required",
  "imageLayerId": "string — required",
  "modelId": "string — required",
  "predictions": [ { "id": 0, "damaged": 1, "unknown": 0.0 } ]
}
```

**Response (200):** `{ "gpkgUrl": "https://...", "count": 2 }`

The endpoint also persists `predictedBuildingCount` and `predictedAt` on the
model. Those two fields — not `gpkgUrl` — are the unambiguous "this model has
predictions" signal: the labeler's **Clear labels** action PUTs
`predictions: []`, which still writes a valid (all-zero) GeoPackage and still
sets `gpkgUrl`, so a cleared model is indistinguishable from a completed one by
`gpkgUrl` alone.

### Prediction Editing

Lets an analyst review a model's building-damage predictions, retune the
thresholds, hand-correct individual buildings, and save the result as a **new
versioned GeoPackage**. See `spec/features/prediction-editing/` and
[ADR-0005](../../spec/architecture/decisions/0005-versioned-derived-prediction-artifacts.md).

> `Model.gpkgUrl` always points at the RAW model output and is never rewritten
> by these endpoints — it is the source every future edit derives from. Saves
> append to `Model.editedPredictions` instead.

Typical call order: `GetPredictionEditSession` →
`PutPreparePredictionTilesQueueMessage` when it reports `tilesReady: false` or
`attrsReady: false` → poll `GetPredictionEditSession` until both are true →
fetch `footprint_pmtiles` and `prediction_attrs` through `GetModelArtifact` →
`PutEditedPredictions` on save.

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetPredictionEditSession` | Everything the editor needs to open a session: prediction flavor, threshold support, building count, artifact readiness, preparation status, and existing versions. |
| PUT | `PutPreparePredictionTilesQueueMessage` | Queue the job that builds the layer's footprint PMTiles and the model's prediction attribute sidecar. |
| PUT | `PutEditedPredictions` | Apply thresholds plus analyst overrides to the raw predictions and store the result as the next numbered version. |
| GET | `GetEditedPredictionVersions` | List a model's saved edited-prediction versions, newest first. |

#### `GET GetPredictionEditSession`

**Query params:** `projectId` (GUID), `imageLayerId` (GUID), `modelId`.

**Response (200):**

```json
{
  "modelId": "5557",
  "flavor": "inference",
  "supportsThreshold": true,
  "defaultThreshold": 0.0,
  "buildingCount": 125430,
  "tilesReady": true,
  "attrsReady": true,
  "predictionTilesStatus": "Processed",
  "predictionTilesStatusMessage": "",
  "versions": [
    {
      "version": 1,
      "gpkgUrl": "https://.../edited_predictions_5557_v1.gpkg",
      "createdAt": "2026-08-21T05:10:48.123456+00:00",
      "createdBy": "analyst@example.com",
      "threshold": 0.5,
      "unknownThreshold": 0.0,
      "editedCount": 53,
      "sourceGpkgUrl": "https://.../raw.gpkg"
    }
  ]
}
```

- `flavor` / `supportsThreshold` are read from the model's raw prediction
  GeoPackage. Trained inference writes a continuous `damage_pct_0m`, so
  thresholding is meaningful (`"inference"`, `supportsThreshold: true`). The
  interactive labeler writes a degenerate 0.0/1.0 copy of `damaged`
  (`"embedding"`, `supportsThreshold: false`) — the UI hides the slider.
- `defaultThreshold` is `0.0` for both flavors. Comparisons downstream are
  strictly greater-than, so `0.0` reproduces exactly what each producer already
  stored (the inference GeoPackage derives `damaged` from `damage_pct_0m > 0`).
- `tilesReady` / `attrsReady` report whether the layer's footprint PMTiles and
  the model's prediction attribute sidecar exist yet. Building them needs
  `tippecanoe`, which ships only in the training image, so they are produced by
  a queued job — never inline in this handler. **This route is read-only:** when
  either flag is false the UI requests the work with
  [`PutPreparePredictionTilesQueueMessage`](#put-putpreparepredictiontilesqueuemessage)
  and then polls here.
- `predictionTilesStatus` is `Model.predictionTilesStatus` — `Queued`,
  `InProgress`, `Processed`, `Failed`, or `null` when preparation has never been
  requested. It lets the UI tell "still building" from "failed" instead of
  polling forever; `predictionTilesStatusMessage` carries the job's appended
  progress/failure lines (empty string when there are none).
- `versions` is `Model.editedPredictions` sorted by version descending.

| Code | Condition |
|------|-----------|
| 400 | Missing or malformed `projectId`, `imageLayerId`, or `modelId` |
| 404 | Model or image layer not found, or the model has no raw prediction GeoPackage |
| 500 | Metadata or storage failure |

#### `PUT PutPreparePredictionTilesQueueMessage`

Queues the preparation job behind the editor's read path: the layer's
geometry-only footprint PMTiles (`ImageLayer.footprintPmtilesUrl`, shared by
every model on the layer) and the model's columnar prediction attribute sidecar
(`Model.predictionAttrsUrl`). Both are produced by
`hastegeo.workflows.prepare_prediction_tiles`, which shells out to
`tippecanoe` — present only in the training image — so this route never does
the work inline, it only asks for it. The
`prediction-edit-prep-queue` trigger in `hastefuncqueues` runs the job through
the training pool and writes the two URLs back.

**Request:**

```json
{
  "projectId": "string — required, GUID",
  "imageLayerId": "string — required, GUID",
  "modelId": "string — required",
  "force": false
}
```

- `force` (default `false`) rebuilds both artifacts even when they already
  exist, and re-queues even when a job is already in flight. Use it after
  predictions are regenerated, which leaves stale artifacts behind.

**Response (200):**

```json
{
  "modelId": "5557",
  "queued": true,
  "tilesReady": false,
  "attrsReady": false,
  "status": "Queued",
  "statusMessage": "\n2026-08-21T05:10:48.123456+00:00: Queued for prediction tile preparation"
}
```

- `queued` says whether a message was actually put on the queue. It is `false`
  — with `status: "Processed"` — when both artifacts already exist, so opening
  the editor on a prepared model costs no Batch task. It is also `false` when a
  job for this model is already `Queued`/`InProgress`, so a double-click or a
  retry cannot submit a duplicate job.
- `tilesReady` / `attrsReady` describe the state **at request time**; they flip
  to `true` once the queued job finishes. Poll
  [`GetPredictionEditSession`](#get-getpredictioneditsession) (or this route)
  until then.
- `status` / `statusMessage` are `Model.predictionTilesStatus` and
  `Model.predictionTilesStatusMessage`, persisted on the model so every poller
  sees the same state.

| Code | Condition |
|------|-----------|
| 400 | Invalid JSON, non-GUID `projectId`/`imageLayerId`, non-numeric `modelId`, or non-boolean `force` |
| 404 | Model or image layer not found; model has no raw prediction GeoPackage (`gpkgUrl`); layer has no cached building footprints — in either case there is nothing to tile |
| 500 | Metadata or queue failure |

Requesting preparation is idempotent: a repeat call while the job runs returns
the current state without enqueueing, and a repeat call on a prepared model
leaves the model document unchanged.

#### `PUT PutEditedPredictions`

**Request:**

```json
{
  "projectId": "string — required, GUID",
  "imageLayerId": "string — required, GUID",
  "modelId": "string — required",
  "threshold": 0.5,
  "unknownThreshold": 0.0,
  "overrides": [ { "id": 12, "class": "Damaged" } ]
}
```

- `threshold` / `unknownThreshold` are **fractions in `[0.0, 1.0]`**, not
  percentages, and both default to `0.0`.
- `overrides[].id` is the zero-based **row index** of the building in the
  prediction GeoPackage (the positional join key used throughout the pipeline).
  It must be a non-negative integer and may appear at most once.
- `overrides[].class` is one of `Damaged`, `NotDamaged`, `Unknown`.
- Derivation precedence per building: an explicit override wins, else
  `unknown > unknownThreshold` → `Unknown`, else `damage > threshold` →
  `Damaged`, else `NotDamaged`.

**Response (200):**

```json
{
  "version": 2,
  "gpkgUrl": "https://.../edited_predictions_5557_v2.gpkg",
  "editedCount": 53
}
```

The stored GeoPackage keeps every source column and row **in source order**
(the downstream join is positional) and adds `edited_class`, `edit_threshold`,
and `overture_id`; `damaged` is rewritten to agree with the final class. The
new `EditedPredictionVersion` is appended to `Model.editedPredictions` with
`createdAt` (UTC ISO-8601) and `createdBy` (from the Static Web Apps client
principal when present).

| Code | Condition |
|------|-----------|
| 400 | Invalid JSON, non-GUID `projectId`/`imageLayerId`, threshold outside `[0,1]`, unknown class, negative or duplicate override id |
| 404 | Model or image layer not found, no raw prediction GeoPackage, or no cached building footprints for the layer |
| 422 | Predictions and footprints do not line up row for row (the positional join would be corrupt) |
| 500 | Blob, metadata, or geospatial write failure |

Override ids outside `[0, buildingCount)` are ignored and logged rather than
rejected, so a stale editor session cannot fail an otherwise valid save.

#### `GET GetEditedPredictionVersions`

**Query params:** `projectId` (GUID), `modelId`.

**Response (200):** `{ "versions": [ ...same shape as above... ] }`, newest
version first; `[]` when the model has never been edited. Returns 400 on
malformed parameters and 404 when the model does not exist.

### Model artifacts

#### `GET GetModelArtifact`

Streams a large browser artifact through the function app using managed
identity. A direct `*.blob.core.windows.net` SAS URL only works from IPs on the
storage firewall allowlist, so the browser fetches same-origin `/api` and the
function app does the blob I/O server-side. `Range` is honored (`206` partial
content, `416` when unsatisfiable) so `pmtiles.js` can do partial reads.

**Query params:** `projectId` (GUID), `modelId`, `kind`, plus optional
`imageLayerId` (GUID) for layer-scoped kinds.

| `kind` | Source field | Content type | Notes |
|--------|--------------|--------------|-------|
| `pmtiles` | `Model.pmtilesUrl` | `application/octet-stream` | Interactive labeler footprint tiles. |
| `sidecar` | `Model.featuresSidecarUrl` | `application/octet-stream` | Per-building embedding vectors. |
| `geojson` | `Model.embeddingsGeoJSONUrl` | `application/geo+json` | |
| `gpkg` | `Model.gpkgUrl` | `application/geopackage+sqlite3` | Served as a download attachment. |
| `prediction_attrs` | `Model.predictionAttrsUrl` | `application/json` | Columnar prediction attribute sidecar for the prediction editor. |
| `footprint_pmtiles` | `ImageLayer.footprintPmtilesUrl` | `application/vnd.pmtiles` | Geometry-only footprint tiles, shared by every model on that layer. Pass `imageLayerId` to select the layer explicitly; it defaults to the model's own image layer. |

The sidecar payload is columnar and index-aligned with the prediction
GeoPackage rows:

```json
{ "n": 3, "ids": [0, 1, 2], "overtureIds": ["08b...", "08c...", "08d..."],
  "damage": [0.0, 0.42, 0.8], "unknown": [0.0, 0.2, 0.0], "damaged": [0, 1, 1] }
```

| Code | Condition |
|------|-----------|
| 400 | Missing/malformed `projectId`, `modelId`, `kind`, or an `imageLayerId` that is neither supplied nor resolvable from the model |
| 404 | Model or image layer not found, or the artifact is not available yet |
| 416 | Requested range starts past the end of the artifact |
| 502 | Blob read failure |

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

### Data Publishing

Publish HASTE artifacts to external catalogs. All publishing routes require an
authenticated caller; mutations additionally require the `contributors` or
`administrators` role, and every response uses the shared publishing error
envelope (`{"error": {"code": ..., "message": ...}}`). See
`spec/features/data-publishing/`.

| Method | Route | Description |
|--------|-------|-------------|
| GET | `GetPublishingProviders` | Publishing providers registered and currently available. |
| GET | `GetPublishDatasetOptions` | Publishable artifacts and target options for a project. Requires `projectId`. |
| GET | `GetPublishedDatasets` | Published datasets, filterable by project. |
| GET | `GetPublishedDataset` | A single published dataset by id. |
| PUT | `PutPublishDatasetQueueMessage` | Queue a publish job for an artifact. |
| PUT | `PutRetryPublishedDatasetQueueMessage` | Re-queue a failed publish job. |
| DELETE | `DeletePublishedDataset` | Withdraw/delete a published dataset. |

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
