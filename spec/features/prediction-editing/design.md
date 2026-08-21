# Technical Design: Prediction Editing

**Contents:** [Overview](#overview) · [Architecture](#architecture) · [API Design](#api-design) · [Behavior & Logic](#behavior--logic) · [Configuration](#configuration) · [Observability](#observability) · [Open Questions](#open-questions)

## Overview

Prediction editing adds a dedicated React screen for full-building prediction
review. The screen reads footprint geometry from PMTiles, reads prediction
attributes from a columnar JSON sidecar, lets an analyst set class overrides,
and saves each edit as a new derived GeoPackage version. Reference the HASTE
architecture in `spec/architecture/overview.md`; this design keeps Azure
Functions as thin HTTP wrappers and moves data manipulation into `hastegeo`.

The raw prediction GeoPackage remains immutable. Existing downstream consumers
continue to use the raw `Model.gpkgUrl`; edited versions are produced, listed,
and downloadable only.

## Architecture

### Component Diagram

```
┌──────────────────────────────┐
│ React UI                     │
│ Model row Edit button        │
│ PredictionEditor page        │
│ Azure Maps + PMTiles         │
└──────────────┬───────────────┘
               │ GET session / PUT prep / attrs / tiles
               ▼
┌──────────────────────────────┐     metadata      ┌────────────────────┐
│ hastefuncapi                 │◀─────────────────▶│ Cosmos metadata     │
│ GetPredictionEditSession     │                   │ Project/Layer/Model │
│ PutPreparePredictionTiles... │
│ PutEditedPredictions         │                   └────────────────────┘
│ GetEditedPredictionVersions  │
│ GetModelArtifact kinds       │
└───────┬───────────────┬──────┘
        │ SAS/download  │ queue after explicit PUT prep request
        ▼               ▼
┌──────────────────┐  ┌────────────────────────────┐
│ Blob Storage     │  │ hastefuncqueues             │
│ raw GPKG         │  │ prediction-edit-prep queue  │
│ edited GPKG vN   │  └─────────────┬──────────────┘
│ PMTiles + attrs  │                │ run training image workflow
└──────────────────┘                ▼
                         ┌────────────────────────────┐
                         │ hastegeo workflow          │
                         │ fiona/geopandas +          │
                         │ tippecanoe PMTiles         │
                         └────────────────────────────┘
```

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Prediction edit engine | `hastelib/src/hastegeo/core/processors/prediction_edits.py` | Apply overrides and thresholds, derive final classes, allocate the next version, and store edited GeoPackages | Python / Fiona |
| Prediction schema utilities | `hastelib/src/hastegeo/core/utils/predictions.py` | Normalize trained-inference vs embedding GeoPackage schemas, preserve row order, and resolve Overture ids positionally | Python / Fiona |
| Prediction HTTP wire models | `hastelib/src/hastegeo/core/models/predictions.py` | Transport-only Pydantic request bodies for save and prep routes; kept out of persisted project schemas | Python / Pydantic |
| Prediction edit models | `hastelib/src/hastegeo/core/models/projects.py` | `EditedPredictionVersion`; new optional `Model` and `ImageLayer` fields | Python / Pydantic |
| Prediction edit prep workflow | `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py` | Build footprint PMTiles and prediction attribute sidecar from the raw prediction GeoPackage and layer footprints | Python / tippecanoe |
| Prediction tiles job processor | `hastelib/src/hastegeo/core/processors/prediction_tiles.py` | Decide whether tiles/sidecar are missing, submit the workflow to the training image through `UnifiedRunner`, persist artifact URLs | Python |
| Queue trigger | `api/hastefuncqueues/function_app.py` | Consume prediction-edit-prep messages and invoke the workflow through the existing runner pattern | Azure Functions |
| Prediction edit page | `ui/src/Components/PredictionEditor/PredictionEditor.jsx` | Full-screen editor with Azure Maps, PMTiles, filters, traversal, overrides, threshold slider, and save action | React / Fluent UI / Azure Maps |
| Prediction edit helpers | `ui/src/Components/PredictionEditor/predictionClassify.js`, `ui/src/Components/PredictionEditor/predictionPrep.js` | Class derivation, sidecar loading, counts, selection state, request shaping, and prep polling decisions | JavaScript |
| Shared PMTiles protocol | `ui/src/util/pmtiles.js` | Single process-wide PMTiles protocol instance and in-memory source used by Azure Maps screens | JavaScript / PMTiles |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| Artifact types | `hastelib/src/hastegeo/core/config.py` | Add `EDITED_PREDICTIONS_GPKG`, `PREDICTION_ATTRS`, and `LAYER_FOOTPRINT_PMTILES` templates |
| Model schema | `hastelib/src/hastegeo/core/models/projects.py` | Add `editedPredictions`, `predictedBuildingCount`, `predictedAt`, `predictionAttrsUrl`, `predictionTilesJob`, `predictionTilesStatus`, and `predictionTilesStatusMessage`; keep `gpkgUrl` as the raw prediction pointer |
| Image layer schema | `hastelib/src/hastegeo/core/models/projects.py` | Add `footprintPmtilesUrl` for layer-level footprint tiles |
| API module | `api/hastefuncapi/function_app.py` | Add four thin prediction-editing endpoints and extend `GetModelArtifact` artifact-kind dispatch |
| Trained model row | `ui/src/Components/ProjectManagement/ModelResultsButton.jsx` | Add **Edit** button enabled when `inferenceStatus === "Processed" && gpkgUrl` |
| Embedding model row | `ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx` | Add **Edit** button enabled when `gpkgUrl && predictedBuildingCount > 0` |
| App routing | `ui/src/Components/AppBody.jsx` | Register `/edit-predictions/:projectId/:imageLayerId/:modelId` |
| Existing editor references | `ui/src/Components/BuildingValidation/BuildingValidation.jsx`, `ui/src/Components/InteractiveLabeler/InteractiveLabeler.jsx`, `ui/src/util/pmtiles.js` | Reuse interaction patterns: filters, prev/next traversal, PMTiles in-memory source, feature-state coloring, and box-select; share the PMTiles protocol singleton |

## API Design

The route names follow the current Azure Functions convention in
`function_app.py`. Endpoints use `func.AuthLevel.FUNCTION` and must delegate
non-HTTP logic to `hastegeo`.

### hastefuncapi Endpoints

#### `GET /api/GetPredictionEditSession`

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Return everything the UI needs to decide whether the editor can
load. The endpoint uses `projectId` to load the image layer and model,
distinguishes trained inference from embedding predictions by reading the raw
GeoPackage, and reports whether the PMTiles and attribute sidecar already exist.
It is side-effect-free: it does not enqueue preparation work. When preparation
is missing, the UI calls `PutPreparePredictionTilesQueueMessage` and then polls
this endpoint.

**Query parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `projectId` | string | yes | Project metadata partition key. |
| `imageLayerId` | string | yes | Image layer that owns the source building footprints. |
| `modelId` | string | yes | Model whose raw `gpkgUrl` supplies predictions. |

**Response (200):**

```json
{
  "modelId": "12345",
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
      "gpkgUrl": "https://...",
      "createdAt": "2026-08-21T05:10:48Z",
      "createdBy": "analyst@example.com",
      "threshold": 0.1,
      "unknownThreshold": 0.0,
      "editedCount": 53,
      "sourceGpkgUrl": "https://...raw.gpkg"
    }
  ]
}
```

For embedding models, `flavor` is `"embedding"` and `supportsThreshold` is
`false`; the UI must hide the threshold slider.

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Missing or malformed `projectId`, `imageLayerId`, or `modelId` |
| 404 | Model, image layer, or raw prediction GeoPackage not found |
| 500 | Storage or metadata failure |

#### `PUT /api/PutPreparePredictionTilesQueueMessage`

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Queue the job that builds the layer footprint PMTiles and the
model prediction attribute sidecar. This route is the only HTTP endpoint that
requests prediction-edit preparation; `GetPredictionEditSession` remains
read-only.

**Request:**

```json
{
  "projectId": "string — required",
  "imageLayerId": "string — required",
  "modelId": "string — required",
  "force": "bool — optional; default false"
}
```

**Response (200):**

```json
{
  "modelId": "12345",
  "queued": true,
  "tilesReady": false,
  "attrsReady": false,
  "status": "Queued",
  "statusMessage": "\n2026-08-21T05:10:48+00:00: Queued for prediction tile preparation"
}
```

**Semantics:**

- When both artifacts are already ready and `force` is false, the response has
  `queued: false`, `tilesReady: true`, `attrsReady: true`, and nothing is
  enqueued.
- When `Model.predictionTilesStatus` is already `Queued` or `InProgress` and
  `force` is false, the response has `queued: false` and no duplicate message is
  enqueued.
- Otherwise the model status is set to `Queued` and exactly one message is put
  on `prediction-edit-prep-queue`.
- `force: true` rebuilds even when artifacts exist or a previous job is in
  flight.

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Invalid JSON or validation failure for `projectId`, `imageLayerId`, `modelId`, or `force` |
| 404 | Model or image layer not found; no raw `Model.gpkgUrl`; or no `ImageLayer.buildingFootprintsUrl` to prepare from |
| 500 | Metadata or queue failure |

#### `PUT /api/PutEditedPredictions`

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Apply a threshold and explicit user overrides to the source
prediction GeoPackage, write a new edited GeoPackage, upload it under the next
numbered version, and append an `EditedPredictionVersion` entry to the `Model`.
The endpoint is synchronous in v1, but all geospatial work must live in
`hastegeo`.

**Request:**

```json
{
  "projectId": "string — required",
  "imageLayerId": "string — required",
  "modelId": "string — required",
  "threshold": "number — optional; default 0.0",
  "unknownThreshold": "number — optional; default 0.0",
  "overrides": [
    { "id": "integer row id", "class": "Damaged | NotDamaged | Unknown" }
  ]
}
```

**Response (200):**

```json
{
  "version": 2,
  "gpkgUrl": "https://.../edited_predictions_12345_v2.gpkg",
  "editedCount": 53
}
```

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Invalid JSON, threshold outside `[0,1]`, unknown threshold outside `[0,1]`, invalid class, duplicate override ids |
| 404 | Model, image layer, raw predictions, or source footprints not found |
| 422 | Source prediction and footprint GeoPackages do not line up row for row |
| 500 | Blob, metadata, or geospatial write failure |

Override ids outside the source row range are ignored and logged rather than
rejected. The response `editedCount` counts only overrides that matched a row.

#### `GET /api/GetEditedPredictionVersions`

**Auth:** `func.AuthLevel.FUNCTION`

**Query parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `projectId` | string | yes | Project metadata partition key. |
| `modelId` | string | yes | Model id. |

**Response (200):**

```json
{
  "versions": [
    {
      "version": 1,
      "gpkgUrl": "https://...",
      "createdAt": "2026-08-21T05:10:48Z",
      "createdBy": "analyst@example.com",
      "threshold": 0.1,
      "unknownThreshold": 0.0,
      "editedCount": 53,
      "sourceGpkgUrl": "https://...raw.gpkg"
    }
  ]
}
```

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Missing or malformed `projectId` or `modelId` |
| 404 | Model not found |
| 500 | Metadata read failure |

#### `GET /api/GetModelArtifact` (modified)

**Auth:** `func.AuthLevel.FUNCTION`

Adds two `kind` values:

| Kind | Required params | Returns |
|---|---|---|
| `footprint_pmtiles` | `projectId`, `imageLayerId`, `modelId` | Streamed bytes for `footprints_${imageLayerId}.pmtiles` |
| `prediction_attrs` | `projectId`, `modelId` | JSON sidecar for `prediction_attrs_${modelId}` |

The sidecar response uses the columnar format below. Arrays must be the same
length and order as the source prediction GeoPackage rows.

```json
{
  "n": 3,
  "ids": [0, 1, 2],
  "overtureIds": ["08b...", "08c...", "08d..."],
  "damage": [0.0, 0.42, 0.8],
  "unknown": [0.0, 0.2, 0.0],
  "damaged": [0, 1, 1]
}
```

### Queue Messages (hastefuncqueues)

#### Queue: `prediction-edit-prep-queue`

**Message Schema:**

```json
{
  "projectId": "string",
  "imageLayerId": "string",
  "modelId": "string",
  "sourceGpkgUrl": "string",
  "sourceFootprintsUrl": "string",
  "force": false
}
```

**Trigger behavior:** The worker downloads the source footprints and raw
prediction GeoPackage, validates equal row count and positional row order,
writes or refreshes `footprints_${imageLayerId}.pmtiles` when missing, writes
`prediction_attrs_${modelId}` from prediction columns, uploads both artifacts,
and updates `ImageLayer.footprintPmtilesUrl`, `Model.predictionAttrsUrl`,
`Model.predictedBuildingCount`, `Model.predictedAt`,
`Model.predictionTilesJob`, `Model.predictionTilesStatus`, and
`Model.predictionTilesStatusMessage`.

Tile creation must run in the queued worker because `tippecanoe` is installed in
the training image only (`docker/training/env/env.yml:11`). Existing PMTiles
creation in `embed_buildings.py` is the invocation pattern to mirror
(`hastelib/src/hastegeo/workflows/embed_buildings.py:712-763`).

### Internal Interfaces (hastegeo)

| Module | Function/Class | Signature | Description |
|---|---|---|---|
| `core/models/projects.py` | `EditedPredictionVersion` | `BaseModel` | Embedded version metadata on `Model`; see [data-model.md](data-model.md#modified-document-schema). |
| `core/models/predictions.py` | `PredictionOverrideRequest`, `EditedPredictionsRequest`, `PreparePredictionTilesRequest` | `BaseModel` | Transport-only HTTP request bodies; mirrors the `PublishRequest` / `PublishedDataset` split by keeping wire contracts out of persisted `projects.py` schemas. |
| `core/utils/predictions.py` | `read_predictions` | `(path: str, footprints_path: Optional[str] = None) -> PredictionSet` | Detects `inference` vs `embedding`, normalizes row attributes, and resolves Overture ids by positional row order. |
| `core/processors/prediction_edits.py` | `apply_edits` | `(src_gpkg: str, dst_gpkg: str, threshold: float, unknown_threshold: float, overrides: dict[int, str], footprints_path: Optional[str]) -> EditSummary` | Applies class derivation, preserves row order, and writes the edited GeoPackage. |
| `core/processors/prediction_edits.py` | `derive_class`, `next_version`, `store_edited_version` | helper functions | Compute final class, allocate the next version number, and store `edited_predictions_${modelId}_v${version}.gpkg`. |
| `core/processors/prediction_tiles.py` | `needs_preparation`, `request_preparation` | `(model: Model, image_layer: ImageLayer, force: bool = False) -> dict` | Decide whether PMTiles/sidecar artifacts are ready and enqueue at most one prep message for the explicit PUT route. |
| `core/processors/prediction_tiles.py` | `PredictionTilesPostprocessor` | class | Submit, poll, and finalize the queued training-image workflow. |
| `hastegeo/workflows/prepare_prediction_tiles.py` | `run` | `(config: dict, output_dir: str) -> dict` | Builds footprint PMTiles and the prediction attribute JSON sidecar. |
| `api/hastefuncapi/function_app.py` | `GetModelArtifact` | HTTP route | Adds `footprint_pmtiles` and `prediction_attrs` kinds. |

## Behavior & Logic

### Core Flow

1. Analyst sees an **Edit** button in each model row.
2. For trained inference, the button is enabled only when
   `model.inferenceStatus === "Processed" && model.gpkgUrl`.
3. For embedding, the button is enabled only when
   `model.gpkgUrl && model.predictedBuildingCount > 0` to avoid the current
   ambiguity where an empty prediction save can still set `gpkgUrl`.
4. The UI navigates to
   `/edit-predictions/:projectId/:imageLayerId/:modelId`.
5. The screen calls `GetPredictionEditSession`.
6. If `tilesReady` or `attrsReady` is false, the screen calls
   `PutPreparePredictionTilesQueueMessage`; that route enqueues
   `prediction-edit-prep-queue` unless artifacts are already ready or a job is
   already in flight. The screen shows a preparation state and polls the
   session endpoint.
7. Once ready, the UI fetches `footprint_pmtiles` and `prediction_attrs` through
   `GetModelArtifact`.
8. Azure Maps displays PMTiles footprints. Feature-state coloring is computed
   from the sidecar, current threshold, unknown threshold, and explicit
   overrides.
9. The analyst clicks or ctrl+drag box-selects buildings, filters by
   `Damaged`, `NotDamaged`, `Unknown`, or `edited`, and uses prev/next traversal.
10. On save, the UI calls `PutEditedPredictions` with the threshold,
    unknown threshold, and only explicit overrides.
11. The backend writes `edited_predictions_${modelId}_v${version}.gpkg`, appends
    version metadata, and returns `{ version, gpkgUrl, editedCount }`.
12. The UI refreshes the version list. Raw `Model.gpkgUrl` remains unchanged.

### Existing implementation constraints

- Trained inference writes `id`, `damage_pct_0m`, `damage_pct_10m`,
  `damage_pct_20m`, `damaged`, and `unknown_pct` in the raster CRS with the
  default layer name (`docker/training/code/merge_with_building_footprints.py:221-231`).
  The `damaged` column is currently hard-coded as `damage_pct_0m > 0`
  (`docker/training/code/merge_with_building_footprints.py:254`).
- The embedding workflow writes predictions through `PutBuildingPredictions`.
  It uses layer name `"predictions"`, adds `area`, and sets `damage_pct_0m` to a
  0.0/1.0 copy of `damaged`, which makes thresholding meaningless for embedding
  models (`api/hastefuncapi/function_app.py:2638-2786`).
- The prediction-to-Overture join is positional row order, not an id. Both the
  assessment utility and the API build Overture ids by reading the footprints in
  order and indexing with the prediction row id
  (`hastelib/src/hastegeo/core/utils/assessment.py:376-395`,
  `api/hastefuncapi/function_app.py:4116-4133`). Edited GeoPackages must keep
  row order exactly and also write an explicit `overture_id` column.
- `GetBuildingFootprintsGeoJSON` is only a sampled preview path, capped at 2,000
  features (`api/hastefuncapi/function_app.py:3626`,
  `api/hastefuncapi/function_app.py:3645-3663`). Prediction editing requires a
  complete PMTiles + sidecar data path.
- PMTiles currently exist only for the embedding workflow through
  `ArtifactTypes.BUILDING_PMTILES` and the embedding processor
  (`hastelib/src/hastegeo/core/config.py:153`,
  `hastelib/src/hastegeo/core/processors/embedding.py:239`). Trained models
  need the new `LAYER_FOOTPRINT_PMTILES` artifact path.
- Existing row gating differs by workflow: trained results key off processed
  inference state, while embedding rows treat any `gpkgUrl` as predictions
  (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:43-46`,
  `ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:86`). This feature
  adds `predictedBuildingCount` and `predictedAt` to remove ambiguity.

### Class derivation rule

The editor supports exactly three classes. Recompute each row at save time using
source prediction values plus explicit user overrides:

```text
final_class = override if the row was explicitly overridden by the user, else
              "Unknown"    if unknown_fraction > unknown_threshold (default 0.0), else
              "Damaged"    if damage_fraction > threshold, else
              "NotDamaged"
```

The written `damaged` integer column is `1` when
`final_class == "Damaged"`; otherwise it is `0`. The edited GeoPackage also
writes `edited_class` (string), `edit_threshold` (float), and `overture_id`
(string). Row order must be preserved exactly from the source prediction
GeoPackage.

### UI behavior

- The screen uses Azure Maps with PMTiles loaded through the existing in-memory
  protocol pattern from `InteractiveLabeler.jsx`.
- Styling uses Fluent UI `makeStyles` and `tokens` so the editor works in dark
  mode. Hard-coded hex colors are not allowed for semantic UI colors.
- Feature-state colors update live when overrides or thresholds change; the
  source PMTiles are not regenerated in the browser.
- The right panel shows counts for `Damaged`, `NotDamaged`, `Unknown`, and
  `edited`, plus filters and prev/next traversal modeled on
  `BuildingValidation.jsx`.
- The threshold slider appears only when `supportsThreshold` is true. It shows
  how many buildings would flip relative to the current saved/default state.
- Embedding models can still be manually reclassified, but do not display the
  slider.

### Edge Cases

| Case | Expected Behavior |
|---|---|
| Missing raw `Model.gpkgUrl` | Edit button disabled; direct session request returns 404. |
| Trained inference processed but no `gpkgUrl` | Edit button disabled because the full prediction GeoPackage is unavailable. |
| Embedding `gpkgUrl` exists but `predictedBuildingCount` is `0` or missing | Edit button disabled; a direct session request still reads the raw GeoPackage if present, so UI gating is the protection against empty embedding saves. |
| PMTiles or sidecar missing | Session endpoint returns `tilesReady: false` or `attrsReady: false`; UI calls `PutPreparePredictionTilesQueueMessage` and then polls with a preparation message. |
| Source prediction and footprint row counts differ | Save returns 422; prep records a failed `predictionTilesStatus` with a row-count message; no edited version is appended. |
| Duplicate override ids | PUT returns 400; client must de-duplicate before retrying. |
| Override id outside source range | Save succeeds; the override is ignored and not counted in `editedCount`. |
| Concurrent saves | Known limitation: backend uses `next_version` plus a metadata save without optimistic concurrency, so concurrent saves can collide instead of returning 409. |
| Invalid thresholds | PUT returns 400 for values outside `[0,1]`. |
| Very large layers | UI avoids GeoJSON; prep/save still read whole GeoPackages and must expose progress/failure logs. |

### Error Handling

| Error Condition | Response | Recovery |
|---|---|---|
| Prep queue enqueue fails | `PutPreparePredictionTilesQueueMessage` returns 500 | Retry the prep request; the route is idempotent by readiness/status. |
| PMTiles generation fails | Session continues to report not ready with status details in logs | Queue retry/dead-letter; user can retry opening the editor. |
| Attribute sidecar missing or invalid | UI blocks editing and reports a load failure | Regenerate prep artifacts with `force: true`. |
| Blob upload timeout on edited GeoPackage | `PutEditedPredictions` returns 500 | Retry save; if a blob exists without model metadata, next version allocation must not reuse it. |
| Metadata conflict appending version | Not detected in the current implementation | Follow up with ETag/lease-based optimistic concurrency before relying on multi-analyst collision safety. |

### Known limitations / follow-ups

- `PutEditedPredictions` does not implement the 409 conflict response that the
  original draft proposed. `next_version` plus `MetadataProcessor.save` is a
  read-modify-write sequence with no ETag, lease, or retry-safe compare step.
- API-level integration tests for the prediction-editing routes are not present;
  `api/hastefuncapi/tests/` contains only `test_publishing_routes.py`. Current
  automated coverage is at the processor, workflow, wire-model, and UI helper
  level.
- `infra/modules/functions.bicep` does not include an explicit app-setting row
  for `PREDICTION_EDIT_PREP_QUEUE_NAME`. This was intentionally skipped because
  `Config` has a default, the Functions host can create the queue, and changing
  the Bicep without regenerating `infra/main.json` would introduce infra drift.
- No browser or Playwright validation exists for the editor screen; this repo
  currently has no Playwright configuration.

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `prediction_edit_prep_queue_name` | string | `prediction-edit-prep-queue` | `local.settings.json` / App Settings | Queue used to generate missing PMTiles and sidecars. |

No feature flag is implemented in the current branch; the API routes and UI
entry points are present when the branch is deployed. No new third-party
dependency is required. PMTiles support already exists in the UI, and
`tippecanoe` already exists in the training image.

## Observability

- **Logs:** Log session readiness, queued prep requests, source schema flavor,
  row-count validation, version allocation, edit counts, and final artifact urls
  without logging SAS tokens.
- **Metrics:** Track session readiness failures, prep duration, save duration,
  edited GeoPackage size, and edited counts.
- **Queue depth:** Monitor `prediction-edit-prep-queue` depth and dead-letter
  count.
- **Storage:** Alert on failed uploads for PMTiles, sidecars, and edited
  GeoPackages.
- **UI errors:** Surface load, sidecar parse, and save errors in the right panel
  with retry actions.

## Open Questions

- [ ] Should edit application move to an async queue if production layers exceed
      Azure Functions request-timeout or memory budgets?
- [ ] Should edited-version saves use Cosmos ETags, blob leases, or another
      optimistic-concurrency mechanism to prevent concurrent version collisions?
- [ ] Should a future downstream-consumption spec choose a single active edited
      version, or let each report/publish call accept a version id?
