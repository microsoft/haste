# Technical Design: Prediction Editing

**Contents:** [Overview](#overview) · [Architecture](#architecture) · [API Design](#api-design) · [Behavior & Logic](#behavior--logic) · [Configuration](#configuration) · [Observability](#observability) · [Open Questions](#open-questions)

## Overview

Prediction editing is a mode of the existing **View Results** page. The
visualizer already owns the two-map swipe view, raster overlays, imagery
metadata, and results URL; edit mode adds the predicted-footprint vector layer,
right-side edit panel, save action, and version history without navigating away
from `/visualizer/:projectId/:imageLayerId/:modelId`
(`ui/src/Components/AppBody.jsx:73-75`,
`ui/src/Components/Visualizer/Visualizer.jsx:13-28`,
`ui/src/Components/Visualizer/Labels.jsx:117-128`).

The results viewer is vector-first. Both trained inference and embedding models
can render predicted building footprints from the layer/model PMTiles plus the
model's columnar prediction attribute sidecar. The trained-inference rasters
remain optional overlays; embedding models return `null` for those fields because
they do not write COGs (`hastelib/src/hastegeo/core/processors/visualizer.py:4-29`,
`hastelib/src/hastegeo/core/processors/visualizer.py:303-331`,
`hastelib/src/hastegeo/core/models/visualizer.py:55-82`).

The raw prediction GeoPackage remains immutable. Each edit save appends a new
`EditedPredictionVersion` and writes a versioned GeoPackage, while readers use
`resolve_prediction_source` to select the newest edit by default or an explicit
`version` (`0` selects raw). This keeps the ADR's no-mutable-pointer decision
while making edits visible to the visualizer, validation report, and assessment
report (`hastelib/src/hastegeo/core/utils/predictions.py:332-401`,
`api/hastefuncapi/function_app.py:2386-2435`,
`api/hastefuncapi/function_app.py:4677-4688`,
`api/hastefuncapi/function_app.py:5017-5027`).

## Architecture

### Component Diagram

```
┌────────────────────────────────────────────┐
│ React UI                                   │
│ Results menu → /visualizer/...             │
│ Visualizer + Labels pencil / E shortcut    │
│ PredictionEditPanel + vector footprints    │
└──────────────────┬─────────────────────────┘
                   │ GET visualizer / GET session / PUT prep / artifacts / PUT save
                   ▼
┌────────────────────────────────────────────┐     metadata      ┌────────────────────┐
│ hastefuncapi                               │◀─────────────────▶│ Cosmos metadata     │
│ GetVisualizerResults (vector-first)        │                   │ Project/Layer/Model │
│ GetPredictionEditSession                   │                   └────────────────────┘
│ PutPreparePredictionTilesQueueMessage      │
│ PutEditedPredictions                       │
│ GetEditedPredictionVersions                │
│ GetModelArtifact kinds                     │
│ GetValidationReport / GetAssessmentReport  │
└──────────────┬─────────────────┬───────────┘
               │ stream artifacts │ queue after explicit prep request
               ▼                 ▼
┌──────────────────┐   ┌────────────────────────────┐
│ Blob Storage     │   │ hastefuncqueues             │
│ raw GPKG         │   │ prediction-edit-prep queue  │
│ edited GPKG vN   │   └─────────────┬──────────────┘
│ PMTiles + attrs  │                 │ run training image workflow
└──────────────────┘                 ▼
                          ┌────────────────────────────┐
                          │ hastegeo workflow          │
                          │ fiona/geopandas +          │
                          │ tippecanoe PMTiles         │
                          └────────────────────────────┘
```

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Prediction edit engine | `hastelib/src/hastegeo/core/processors/prediction_edits.py` | Apply overrides and thresholds, derive final classes, allocate the next version, and store edited GeoPackages (`hastelib/src/hastegeo/core/processors/prediction_edits.py:1-19`, `hastelib/src/hastegeo/core/processors/prediction_edits.py:226-308`) | Python / Fiona |
| Prediction schema and source utilities | `hastelib/src/hastegeo/core/utils/predictions.py` | Normalize trained-inference vs embedding GeoPackage schemas, preserve row order, resolve Overture ids positionally, and choose raw/newest/explicit edited sources (`hastelib/src/hastegeo/core/utils/predictions.py:4-34`, `hastelib/src/hastegeo/core/utils/predictions.py:318-401`) | Python / Fiona |
| Model readiness utility | `hastelib/src/hastegeo/core/utils/model_readiness.py` | Single server-side readiness rule for model rows, visualizer readiness, and publishing completion (`hastelib/src/hastegeo/core/utils/model_readiness.py:4-25`, `hastelib/src/hastegeo/core/utils/model_readiness.py:132-237`) | Python |
| Visualizer payload builder | `hastelib/src/hastegeo/core/processors/visualizer.py` | Build the vector-first `GetVisualizerResults` payload and nullable raster layers for both workflows (`hastelib/src/hastegeo/core/processors/visualizer.py:215-336`) | Python |
| Prediction HTTP wire models | `hastelib/src/hastegeo/core/models/predictions.py` | Transport-only Pydantic request bodies for save and prep routes; kept out of persisted project schemas | Python / Pydantic |
| Prediction edit models | `hastelib/src/hastegeo/core/models/projects.py` | `EditedPredictionVersion`; new optional `Model` and `ImageLayer` fields (`hastelib/src/hastegeo/core/models/projects.py:343-505`, `hastelib/src/hastegeo/core/models/projects.py:520-529`, `hastelib/src/hastegeo/core/models/projects.py:842-851`) | Python / Pydantic |
| Prediction edit prep workflow | `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py` | Build footprint PMTiles and prediction attribute sidecar from the raw prediction GeoPackage and layer footprints (`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:4-46`, `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:322-416`) | Python / tippecanoe |
| Prediction tiles job processor | `hastelib/src/hastegeo/core/processors/prediction_tiles.py` | Decide whether tiles/sidecar are missing, submit the workflow to the training image through `UnifiedRunner`, persist artifact URLs (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:251-370`, `hastelib/src/hastegeo/core/processors/prediction_tiles.py:475-560`) | Python |
| Queue trigger | `api/hastefuncqueues/function_app.py` | Consume prediction-edit-prep messages and invoke model-scoped or layer-only preparation through the existing runner pattern (`api/hastefuncqueues/function_app.py:861-914`) | Azure Functions |
| Visualizer edit affordance | `ui/src/Components/Visualizer/Labels.jsx` | Pencil/Done button next to Back; disabled-state tooltip (`ui/src/Components/Visualizer/Labels.jsx:8-12`, `ui/src/Components/Visualizer/Labels.jsx:117-128`) | React / Fluent UI |
| Visualizer edit mode | `ui/src/Components/Visualizer/Visualizer.jsx` | Enters/leaves edit mode, hides conflicting rasters while editing, handles unsaved discard dialog, keyboard shortcuts, and edit panel render (`ui/src/Components/Visualizer/Visualizer.jsx:457-605`, `ui/src/Components/Visualizer/Visualizer.jsx:873-921`) | React / Azure Maps |
| Prediction artifact hook | `ui/src/Components/Visualizer/usePredictionArtifacts.js` | Load vector artifacts, request prep, poll readiness, cache versions, and expose active version (`ui/src/Components/Visualizer/usePredictionArtifacts.js:4-24`, `ui/src/Components/Visualizer/usePredictionArtifacts.js:177-221`, `ui/src/Components/Visualizer/usePredictionArtifacts.js:377-459`) | React / PMTiles |
| Prediction footprint hook | `ui/src/Components/Visualizer/usePredictionFootprints.js` | Add footprint layers to both swipe panes, apply feature-state coloring, selection, overrides, save, and discard (`ui/src/Components/Visualizer/usePredictionFootprints.js:4-29`, `ui/src/Components/Visualizer/usePredictionFootprints.js:313-376`, `ui/src/Components/Visualizer/usePredictionFootprints.js:838-902`) | React / Azure Maps |
| Prediction edit panel | `ui/src/Components/Visualizer/PredictionEditPanel.jsx` | Counts, filters, traversal, threshold sliders when supported, save button, Done button, keyboard help, and read-only saved-version history (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:4-16`, `ui/src/Components/Visualizer/PredictionEditPanel.jsx:300-585`) | React / Fluent UI |
| Results decision helpers | `ui/src/Components/Visualizer/predictionResults.js`, `predictionClassify.js`, `predictionPrep.js`, `predictionFootprintMap.js`, `visualizerSwipe.js` | Pure helper logic for payload interpretation, classification, prep polling, map paint expressions, and swipe hints; covered by Node tests (`ui/src/Components/Visualizer/predictionResults.js:20-25`, `ui/src/Components/Visualizer/predictionResults.js:96-103`, `ui/src/Components/Visualizer/predictionResults.js:320-385`) | JavaScript |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| Artifact types | `hastelib/src/hastegeo/core/config.py` | Add `EDITED_PREDICTIONS_GPKG`, `PREDICTION_ATTRS`, and `LAYER_FOOTPRINT_PMTILES` templates; queue config defaults to `prediction-edit-prep-queue` (`hastelib/src/hastegeo/core/config.py:165-172`, `hastelib/src/hastegeo/core/config.py:341-347`) |
| Model schema | `hastelib/src/hastegeo/core/models/projects.py` | Add edited-version, predicted-building, sidecar, and prep-status fields while keeping `gpkgUrl` as the raw prediction pointer (`hastelib/src/hastegeo/core/models/projects.py:431-438`, `hastelib/src/hastegeo/core/models/projects.py:491-529`) |
| Image layer schema | `hastelib/src/hastegeo/core/models/projects.py` | Add `footprintPmtilesUrl` and layer-only tiling status fields (`hastelib/src/hastegeo/core/models/projects.py:758-770`, `hastelib/src/hastegeo/core/models/projects.py:842-851`) |
| API module | `api/hastefuncapi/function_app.py` | Adds prediction-editing endpoints; extends `GetModelArtifact`; updates `GetVisualizerResults`, `GetValidationReport`, and `GetAssessmentReport`; stamps `predictionsReady` on model payloads (`api/hastefuncapi/function_app.py:1400-1510`, `api/hastefuncapi/function_app.py:2296-2435`, `api/hastefuncapi/function_app.py:2920-3420`, `api/hastefuncapi/function_app.py:4607-4688`, `api/hastefuncapi/function_app.py:4929-5027`) |
| Trained model row | `ui/src/Components/ProjectManagement/ModelResultsButton.jsx` | Uses `predictionsReady` to enable View Results and removes the standalone Edit action (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:87-110`) |
| Embedding model row | `ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx` | Adds View Results as the first Results menu item and removes the standalone Edit action (`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:85-130`) |
| App routing | `ui/src/Components/AppBody.jsx` | Keeps `/visualizer/:projectId/:imageLayerId/:modelId`; no `/edit-predictions/...` route is registered (`ui/src/Components/AppBody.jsx:73-75`) |
| Existing editor references | `ui/src/Components/Visualizer/`, `ui/src/util/pmtiles.js` | Visualizer now owns PMTiles loading, feature-state coloring, filters, prev/next traversal, box-select, keyboard shortcuts, and shared PMTiles protocol (`ui/src/Components/Visualizer/usePredictionArtifacts.js:25-32`, `ui/src/Components/Visualizer/usePredictionFootprints.js:313-376`, `ui/src/Components/keyboardShortcuts.js:60-80`) |

## API Design

The route names follow the current Azure Functions convention in
`function_app.py`. Endpoints use `func.AuthLevel.FUNCTION` and delegate non-HTTP
logic to `hastegeo`.

### Model payloads: `predictionsReady`

Every endpoint that returns model objects (`GetProjectDetails`,
`GetLayerDetailView`, and `GetLayerModelsDetails`) stamps a derived
`predictionsReady` boolean in memory. It is not persisted and should not be sent
back in a `PutModel` body (`api/hastefuncapi/function_app.py:785-788`,
`api/hastefuncapi/function_app.py:1262-1266`,
`api/hastefuncapi/function_app.py:1380-1383`). The exact readiness rule is
specified in the API docs and implemented in `model_readiness.py`
(`docs/api/hastefuncapi.md:59-76`,
`hastelib/src/hastegeo/core/utils/model_readiness.py:132-237`).

### hastefuncapi Endpoints

#### `GET /api/GetVisualizerResults`

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Return everything the View Results page needs for one model.
This is the primary read path for both workflows and the data source for the
vector footprint layer. The full response shape is documented in
`docs/api/hastefuncapi.md`; keep that API reference as the contract rather than
restating a divergent schema here (`docs/api/hastefuncapi.md:78-157`).

**Key semantics:**

- `footprintTilesUrl` and `predictionAttrsUrl` are API-relative
  `GetModelArtifact` routes, not blob URLs.
- `predictedDamageLayer` and `predictionsLayer` are nullable. They are normally
  present only for trained-inference models with prediction COGs.
- `predictionsReady` in this payload is stricter than the model-row flag because
  it also requires browser artifacts to exist; `predictionsReadiness` explains
  `ready`, `not_processed`, `no_predictions`, `no_buildings`, or `preparing`.
- `flavor`, `supportsThreshold`, and `buildingCount` come from reading the
  selected prediction GeoPackage. If the file cannot be read, the payload still
  returns imagery and readiness with those fields null.
- `predictionVersion` reports the edited version on the map (`null` for raw),
  and `predictionVersions` returns `Model.editedPredictions` newest first.
- Optional `version` follows the shared reader contract: omit for newest edit,
  `0` for raw, or `N` for a specific edited version
  (`api/hastefuncapi/function_app.py:157-171`,
  `api/hastefuncapi/function_app.py:2386-2435`).

#### `GET /api/GetPredictionEditSession`

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Return the additional data edit mode needs when it opens. The
endpoint uses `projectId` to load the image layer and model, distinguishes
trained inference from embedding predictions by reading the selected raw
GeoPackage, and reports whether PMTiles and the sidecar already exist. It is
side-effect-free: it does not enqueue preparation work. When preparation is
missing, the UI calls `PutPreparePredictionTilesQueueMessage` and then polls
this endpoint (`api/hastefuncapi/function_app.py:2920-3025`).

**Query parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `projectId` | string | yes | Project metadata partition key. |
| `imageLayerId` | string | yes | Image layer that owns the source building footprints. |
| `modelId` | string | yes | Model whose raw `gpkgUrl` supplies predictions. |

**Response (200):** `modelId`, `flavor`, `supportsThreshold`,
`defaultThreshold`, `buildingCount`, `tilesReady`, `attrsReady`,
`predictionTilesStatus`, `predictionTilesStatusMessage`, and `versions`.
Embedding models return `flavor="embedding"` and `supportsThreshold=false`, so
the UI hides threshold sliders (`api/hastefuncapi/function_app.py:3005-3025`).

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

**Response (200):** `modelId`, `queued`, `tilesReady`, `attrsReady`, `status`,
and `statusMessage`, matching `request_preparation` (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:251-370`).

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

**Description:** Apply a threshold and explicit user overrides to the raw source
prediction GeoPackage, write a new edited GeoPackage, upload it under the next
numbered version, and append an `EditedPredictionVersion` entry to the `Model`.
The endpoint is synchronous in v1, but all geospatial work lives in `hastegeo`
(`api/hastefuncapi/function_app.py:3181-3345`).

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

**Response (200):** `version`, `gpkgUrl`, and `editedCount`.

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Invalid JSON, threshold outside `[0,1]`, unknown threshold outside `[0,1]`, invalid class, duplicate override ids |
| 404 | Model, image layer, raw predictions, or source footprints not found |
| 422 | Source prediction and footprint GeoPackages do not line up row for row |
| 500 | Blob, metadata, or geospatial write failure |

Override ids outside the source row range are ignored and logged rather than
rejected. The response `editedCount` counts only overrides that matched a row
(`hastelib/src/hastegeo/core/processors/prediction_edits.py:293-308`).

#### `GET /api/GetEditedPredictionVersions`

**Auth:** `func.AuthLevel.FUNCTION`

**Query parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `projectId` | string | yes | Project metadata partition key. |
| `modelId` | string | yes | Model id. |

**Response (200):** `{"versions": [EditedPredictionVersion, ...]}`, newest
first. The same helper backs the visualizer payload and the edit session
(`api/hastefuncapi/function_app.py:2912-2917`,
`api/hastefuncapi/function_app.py:3376-3410`).

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Missing or malformed `projectId` or `modelId` |
| 404 | Model not found |
| 500 | Metadata read failure |

#### `GET /api/GetModelArtifact` (modified)

**Auth:** `func.AuthLevel.FUNCTION`

Adds two `kind` values. The route streams bytes through the Function App so auth,
managed identity, and HTTP `Range` support remain central (`api/hastefuncapi/function_app.py:1430-1458`).

| Kind | Required params | Returns |
|---|---|---|
| `footprint_pmtiles` | `projectId`, `imageLayerId`, `modelId` | Streamed bytes for the layer PMTiles, or the embedding model's own `pmtilesUrl` when available (`api/hastefuncapi/function_app.py:1489-1507`) |
| `prediction_attrs` | `projectId`, `modelId` | JSON sidecar for `prediction_attrs_${modelId}` (`api/hastefuncapi/function_app.py:1400-1424`) |

The sidecar response uses the columnar format below. Arrays must be the same
length and order as the source prediction GeoPackage rows
(`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:351-416`).

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

#### `GET /api/GetValidationReport`, `GET /api/GetAssessmentReport` (modified)

Both report endpoints accept optional `version` with the same semantics as
`GetVisualizerResults`: omitted = newest edit or raw fallback, `0` = raw, and
`N` = a specific edited version. Unknown `N` returns 404 and malformed values
return 400 (`api/hastefuncapi/function_app.py:4607-4688`,
`api/hastefuncapi/function_app.py:4929-5027`,
`docs/api/hastefuncapi.md:480-502`).

Important asymmetry: edited GeoPackages rewrite `damaged` but preserve the
producer's original `damage_pct_0m`. `GetValidationReport` builds metrics from
`damaged`, so analyst overrides move validation metrics. `GetAssessmentReport`
feeds `damage_pct_0m` into `compute_assessment_report`, so per-building overrides
do not move its threshold-based damaged counts until a follow-up changes the
assessment data model (`api/hastefuncapi/function_app.py:4808-4827`,
`api/hastefuncapi/function_app.py:5080-5103`,
`hastelib/src/hastegeo/core/utils/assessment.py:150-190`).

### Queue Messages (hastefuncqueues)

#### Queue: `prediction-edit-prep-queue`

**Message Schema:**

```json
{
  "projectId": "string",
  "imageLayerId": "string",
  "modelId": "string — empty selects layer-only preparation",
  "sourceGpkgUrl": "string — empty in layer-only mode",
  "sourceFootprintsUrl": "string",
  "force": false
}
```

**Trigger behavior (model-scoped, `modelId` set):** The worker downloads the
source footprints and raw prediction GeoPackage, validates equal row count and
positional row order, writes or refreshes `footprints_${imageLayerId}.pmtiles`
when missing, writes `prediction_attrs_${modelId}` from prediction columns,
uploads both artifacts, and updates `ImageLayer.footprintPmtilesUrl`,
`Model.predictionAttrsUrl`, `Model.predictedBuildingCount`, `Model.predictedAt`,
`Model.predictionTilesJob`, `Model.predictionTilesStatus`, and
`Model.predictionTilesStatusMessage` (`api/hastefuncqueues/function_app.py:721-827`).

**Trigger behavior (layer-only, `modelId` empty):** The worker downloads the
source footprints only, writes `footprints_${imageLayerId}.pmtiles`, and updates
`ImageLayer.footprintPmtilesUrl`, `ImageLayer.footprintTilesJob`,
`ImageLayer.footprintTilesStatus`, and `ImageLayer.footprintTilesStatusMessage`.
No sidecar is built and no model document is read or written (`api/hastefuncqueues/function_app.py:639-719`,
`api/hastefuncqueues/function_app.py:877-914`).

`ImageryPostProcessor` enqueues the layer-only message as soon as an image layer
completes with cached building footprints and no `footprintPmtilesUrl`. That
enqueue is best effort: a queue failure is logged and imagery preprocessing
still succeeds, because the visualizer/edit preparation path rebuilds tiles on
demand (`hastelib/src/hastegeo/core/processors/imagery.py:249-257`,
`hastelib/src/hastegeo/core/processors/imagery.py:399-441`).

### Internal Interfaces (hastegeo)

| Module | Function/Class | Signature | Description |
|---|---|---|---|
| `core/models/projects.py` | `EditedPredictionVersion` | `BaseModel` | Embedded version metadata on `Model`; see [data-model.md](data-model.md#modified-document-schema). |
| `core/models/predictions.py` | `PredictionOverrideRequest`, `EditedPredictionsRequest`, `PreparePredictionTilesRequest` | `BaseModel` | Transport-only HTTP request bodies. |
| `core/utils/model_readiness.py` | `prediction_readiness`, `predictions_ready`, `annotate_predictions_ready` | `(model, config=None) -> PredictionReadiness/bool/dict` | Single model-readiness rule for UI payloads and publishing (`hastelib/src/hastegeo/core/utils/model_readiness.py:132-237`). |
| `core/utils/predictions.py` | `read_predictions` | `(path: str, footprints_path: Optional[str] = None) -> PredictionSet` | Detects `inference` vs `embedding`, normalizes row attributes, and resolves Overture ids by positional row order. |
| `core/utils/predictions.py` | `resolve_prediction_source`, `describe_prediction_source`, `edited_prediction_versions` | `(model, version=None) -> str/PredictionSource/list` | Implements newest-wins, `version=0` raw, and explicit edited version selection (`hastelib/src/hastegeo/core/utils/predictions.py:318-401`). |
| `core/processors/visualizer.py` | `build_visualizer_results`, `visualizer_readiness`, `raster_layer_urls` | pure payload helpers | Assemble vector-first `GetVisualizerResults` payload and nullable raster layers (`hastelib/src/hastegeo/core/processors/visualizer.py:152-336`). |
| `core/processors/prediction_edits.py` | `apply_edits` | `(src_gpkg, dst_gpkg, threshold, unknown_threshold, overrides, footprints_path=None) -> EditSummary` | Applies class derivation, preserves row order, and writes the edited GeoPackage. |
| `core/processors/prediction_edits.py` | `derive_class`, `next_version`, `store_edited_version` | helper functions | Compute final class, allocate the next version number, and store `edited_predictions_${modelId}_v${version}.gpkg`. |
| `core/processors/prediction_tiles.py` | `needs_preparation`, `request_preparation`, `resolve_tiles_url` | `(model, image_layer, force=False) -> flags/response` | Decide whether PMTiles/sidecar artifacts are ready and enqueue at most one prep message for the explicit PUT route. |
| `core/processors/prediction_tiles.py` | `layer_needs_footprint_tiles`, `enqueue_prediction_tiles`, `PredictionTilesPostprocessor` | helper / postprocessor | Queue and run model-scoped or layer-only tile prep. |
| `core/processors/imagery.py` | `ImageryPostProcessor._enqueue_footprint_tiles` | `() -> None` | Best-effort layer-only enqueue once a completed layer has footprints and no tiles; never raises into imagery prep. |
| `hastegeo/workflows/prepare_prediction_tiles.py` | `run` | `(config: dict, output_dir: str) -> dict` | Builds footprint PMTiles and, when `config["model_id"]` is set, the prediction attribute JSON sidecar. |
| `api/hastefuncapi/function_app.py` | `GetModelArtifact` | HTTP route | Adds `footprint_pmtiles` and `prediction_attrs` kinds. |

## Behavior & Logic

### Core Flow

1. Analyst opens a model's **Results** menu and selects **View**. Trained rows
   and embedding rows both navigate to `/visualizer/:projectId/:imageLayerId/:modelId`.
2. The View item is enabled from server-derived `predictionsReady`, with
   client-side legacy fallbacks for models saved before the field existed.
3. `Visualizer` calls `GetVisualizerResults` without a `version` parameter, so
   the newest edited version is selected by default when edits exist
   (`ui/src/Components/Visualizer/Visualizer.jsx:213-223`).
4. The payload supplies imagery, nullable raster overlays, vector artifact URLs,
   readiness, flavor, threshold support, building count, active version, and
   version history.
5. `usePredictionArtifacts` fetches `prediction_attrs` and `footprint_pmtiles`
   through `GetModelArtifact`. If the payload or artifact response says they are
   missing, it lazily reads `GetPredictionEditSession`, calls
   `PutPreparePredictionTilesQueueMessage`, and polls the session endpoint.
6. `usePredictionFootprints` adds the PMTiles source/layers to both swipe panes,
   then colors features from sidecar attributes, current thresholds, and manual
   overrides.
7. The analyst clicks the pencil next to Back or presses `E` to enter edit mode.
   Rasters are hidden while editing and restored when edit mode exits.
8. The analyst clicks or ctrl+drag box-selects buildings, filters by `Damaged`,
   `NotDamaged`, `Unknown`, or `edited`, and uses prev/next traversal. Keys
   `1`, `2`, and `3` set the selected building's class in edit mode.
9. On save, the UI calls `PutEditedPredictions` with threshold,
   unknownThreshold, and only explicit overrides.
10. The backend writes `edited_predictions_${modelId}_v${version}.gpkg`, appends
    version metadata, and returns `{ version, gpkgUrl, editedCount }`.
11. The UI refreshes the version list and resets the unsaved baseline. Raw
    `Model.gpkgUrl` remains unchanged.
12. `GetVisualizerResults`, `GetValidationReport`, and `GetAssessmentReport`
    use the newest edit on later calls unless the caller pins `version` or passes
    `version=0`.

### Existing implementation constraints

- Trained inference writes `id`, `damage_pct_0m`, `damage_pct_10m`,
  `damage_pct_20m`, `damaged`, and `unknown_pct` in the raster CRS with the
  default layer name. It sets `damaged` to `1` when `damage_pct_0m > 0`
  (`docker/training/code/merge_with_building_footprints.py:221-258`).
- The classic writer can skip footprints outside raster bounds before writing
  predictions, so the positional join can silently lose rows before this feature
  ever sees the GeoPackage (`docker/training/code/merge_with_building_footprints.py:151-190`).
- The embedding workflow writes predictions through `PutBuildingPredictions`. It
  uses layer name `"predictions"`, adds `area`, and sets `damage_pct_0m` to a
  0.0/1.0 copy of `damaged`, which makes thresholding meaningless for embedding
  models (`api/hastefuncapi/function_app.py:2738-2815`).
- Neither producer writes an explicit `overture_id` column. Current reports join
  prediction rows to Overture ids by reading the footprints in order and indexing
  with the prediction row id (`hastelib/src/hastegeo/core/utils/assessment.py:368-395`,
  `api/hastefuncapi/function_app.py:4808-4827`). Edited GeoPackages must keep
  row order exactly and add `overture_id` for auditability.
- `GetBuildingFootprintsGeoJSON` remains only a sampled preview path; prediction
  editing uses complete PMTiles + sidecar data through `GetModelArtifact`.
- PMTiles existed for the embedding workflow through the embedding model's own
  archive. The viewer reuses that archive when available and otherwise uses the
  layer-scoped `ImageLayer.footprintPmtilesUrl`
  (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:202-226`,
  `api/hastefuncapi/function_app.py:1489-1507`).

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
GeoPackage (`hastelib/src/hastegeo/core/processors/prediction_edits.py:246-279`).

### UI behavior

- The screen is the existing Visualizer route; there is no standalone
  `PredictionEditor` directory or `/edit-predictions/...` route in the current
  implementation (`ui/src/Components/AppBody.jsx:73-75`).
- The screen uses Azure Maps with PMTiles loaded through the shared in-memory
  protocol pattern (`ui/src/Components/Visualizer/usePredictionArtifacts.js:201-212`).
- Styling uses Fluent UI `makeStyles` and `tokens` so the editor works in dark
  mode. Hard-coded hex colors are not allowed for semantic UI colors
  (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:72-80`,
  `ui/src/Components/Visualizer/predictionFootprintMap.js:70-95`).
- Feature-state colors update live when overrides or thresholds change; the
  source PMTiles are not regenerated in the browser.
- The right panel shows counts for `Damaged`, `NotDamaged`, `Unknown`, and
  `edited`, plus filters, prev/next traversal, click-action mode, threshold
  controls when supported, saved-version history, Save as new version, and Done
  editing.
- The threshold slider appears only when `supportsThreshold` is true. Embedding
  models can still be manually reclassified, but do not display the slider
  (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:346-397`).
- The saved-version history is read-only in this branch. It shows which version
  is currently on the map but does not refetch when a row is selected
  (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`,
  `ui/src/Components/Visualizer/Visualizer.jsx:213-223`).

### Edge Cases

| Case | Expected Behavior |
|---|---|
| Missing raw `Model.gpkgUrl` | View/edit remains unavailable; direct session request returns 404. |
| Trained inference processed but no `gpkgUrl` and no `predictedDamageLayerUrl` | `predictionsReady` is false; results View is disabled or the visualizer explains there are no predictions. |
| Embedding `gpkgUrl` exists but `predictedBuildingCount` is `0` | `predictionsReady` is false with reason `no_buildings`; the visualizer should not queue a prep job that can never produce buildings (`hastelib/src/hastegeo/core/utils/model_readiness.py:168-198`). |
| Embedding model predates `predictedBuildingCount` | Falls back to `gpkgUrl` so older successful models remain viewable (`hastelib/src/hastegeo/core/utils/model_readiness.py:142-146`). |
| PMTiles or sidecar missing | `predictionsReadiness.reason` is `preparing`; UI requests prep and polls until artifacts are available. |
| Source prediction and footprint row counts differ | Save returns 422; prep records a failed `predictionTilesStatus` with a row-count message; no edited version is appended. |
| Duplicate override ids | PUT returns 400; client must de-duplicate before retrying. |
| Override id outside source range | Save succeeds; the override is ignored and not counted in `editedCount`. |
| Concurrent saves | Known limitation: backend uses `next_version` plus a metadata save without optimistic concurrency, so concurrent saves can collide instead of returning 409. |
| Invalid thresholds | PUT returns 400 for values outside `[0,1]`. |
| Very large layers | UI avoids GeoJSON; prep/save still read whole GeoPackages and must expose progress/failure logs. |
| User exits edit mode with unsaved edits | Visualizer shows a discard-confirmation dialog and either discards or keeps editing (`ui/src/Components/Visualizer/Visualizer.jsx:502-528`). |
| User wants to inspect older edits | API supports `version=N`, but UI selection is not wired; use the API directly or wait for follow-up UI work. |

### Error Handling

| Error Condition | Response | Recovery |
|---|---|---|
| Prep queue enqueue fails | `PutPreparePredictionTilesQueueMessage` returns 500 | Retry the prep request; the route is idempotent by readiness/status. |
| PMTiles generation fails | Visualizer status note reports not ready with status details; session continues to report failure | Queue retry/dead-letter; user can retry with force from the status note. |
| Attribute sidecar missing or invalid | UI blocks editing and reports a load failure | Regenerate prep artifacts with `force: true`. |
| Blob upload timeout on edited GeoPackage | `PutEditedPredictions` returns 500 | Retry save; if a blob exists without model metadata, next version allocation must not reuse it. |
| Metadata conflict appending version | Not detected in the current implementation | Follow up with ETag/lease-based optimistic concurrency before relying on multi-analyst collision safety. |
| Unknown explicit prediction version | Reader returns 404 | Refresh version history or use `version=0` for raw. |
| Malformed prediction version | Reader returns 400 | Fix the query parameter. |

### Known limitations / follow-ups

- UI version switching is not wired. The history is read-only; `predictionVersion`
  reports what is on the map, but selecting another version does not refetch
  (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`,
  `ui/src/Components/Visualizer/Visualizer.jsx:213-223`).
- Edited GeoPackages override `damaged` but preserve the producer's
  `damage_pct_0m`. `GetValidationReport` reads `damaged`, so edits move its
  metrics; `GetAssessmentReport` thresholds `damage_pct_0m`, so per-building
  overrides do not move threshold-based counts (`api/hastefuncapi/function_app.py:4808-4827`,
  `api/hastefuncapi/function_app.py:5080-5103`).
- `PutEditedPredictions` does not implement the 409 conflict response that the
  original draft proposed. `next_version` plus `MetadataProcessor.save` is a
  read-modify-write sequence with no ETag, lease, or retry-safe compare step.
- API-level integration tests for the rewritten handlers are not present.
  Current automated coverage is at the processor, workflow, wire-model, and UI
  helper level.
- No browser or Playwright validation exists for the viewer or edit mode; this
  repo currently has no Playwright configuration or dependency (`ui/package.json:6-15`,
  `ui/package.json:62-75`).
- Two pre-existing correctness risks remain out of scope: the classic workflow
  can drop footprint rows before writing predictions, and neither producer writes
  `overture_id` in the raw prediction GeoPackage (`docker/training/code/merge_with_building_footprints.py:151-190`,
  `docker/training/code/merge_with_building_footprints.py:221-258`,
  `api/hastefuncapi/function_app.py:2738-2815`).
- `infra/modules/functions.bicep` does not include an explicit app-setting row
  for `PREDICTION_EDIT_PREP_QUEUE_NAME`. This was intentionally skipped because
  `Config` has a default, the Functions host can create the queue, and changing
  the Bicep without regenerating `infra/main.json` would introduce infra drift.

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `prediction_edit_prep_queue_name` | string | `prediction-edit-prep-queue` | `local.settings.json` / App Settings / `Config.get_queue_config()` | Queue used to generate missing PMTiles and sidecars (`hastelib/src/hastegeo/core/config.py:341-347`). |

No feature flag is implemented in the current branch; the API routes and UI
entry points are present when the branch is deployed. No new third-party
dependency is required. PMTiles support already exists in the UI, and
`tippecanoe` already exists in the training image.

## Observability

- **Logs:** Log model/readiness decisions, visualizer version selection, queued
  prep requests, source schema flavor, row-count validation, version allocation,
  edit counts, and final artifact URLs without logging SAS tokens.
- **Metrics:** Track `GetVisualizerResults` readiness failures, prep duration,
  save duration, edited GeoPackage size, and edited counts.
- **Queue depth:** Monitor `prediction-edit-prep-queue` depth and dead-letter
  count.
- **Storage:** Alert on failed uploads for PMTiles, sidecars, and edited
  GeoPackages.
- **UI errors:** Surface load, sidecar parse, prep timeout, and save errors in
  the status note or edit panel with retry actions.

## Open Questions

- [ ] Should edit application move to an async queue if production layers exceed
      Azure Functions request-timeout or memory budgets?
- [ ] Should edited-version saves use Cosmos ETags, blob leases, or another
      optimistic-concurrency mechanism to prevent concurrent version collisions?
- [ ] Should the UI implement version switching by refetching
      `GetVisualizerResults?version=N`, by adding a dedicated version-selection
      endpoint, or by keeping the history read-only?
- [ ] Should assessment reports use edited `damaged`, persist edited
      `damage_pct_0m`, expose override-aware counts separately, or keep the
      current threshold-only interpretation?
- [ ] Should raw prediction producers add explicit `overture_id` and stop
      relying on positional joins before this feature is broadly rolled out?
