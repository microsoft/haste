# Data Model: Prediction Editing

**Contents:** [Cosmos DB Changes](#cosmos-db-changes) · [Blob Storage Changes](#blob-storage-changes) · [Data Lake Changes](#data-lake-changes) · [Queue Storage Changes](#queue-storage-changes) · [Azure Batch Changes](#azure-batch-changes) · [Data Flow](#data-flow) · [Migration Plan](#migration-plan) · [Data Volume Estimates](#data-volume-estimates) · [Caching Strategy](#caching-strategy)

## Cosmos DB Changes

### New Containers

No new Cosmos containers. Prediction edit metadata remains embedded in the
existing Model document, and layer PMTiles metadata remains embedded in the
ImageLayer document.

| Container | Partition Key | Description |
|---|---|---|
| — | — | No new container. |

### Modified Containers

| Container | Change | Migration Needed? |
|---|---|---|
| Model metadata | Keep `gpkgUrl` as raw, keep raw/model-scoped `predictionAttrsUrl`, and extend each `EditedPredictionVersion` with a per-version sidecar URL | no — nullable/defaulted fields stay backward-compatible (`hastelib/src/hastegeo/core/models/projects.py:343-389`, `hastelib/src/hastegeo/core/models/projects.py:491-535`) |
| ImageLayer metadata | No schema change for version selection; existing `footprintPmtilesUrl` remains shared by all model versions on the layer | no |

### New Document Schema

**Container:** existing Model metadata document
**Partition key:** `projectId`

`EditedPredictionVersion` remains an embedded append-only list entry on `Model`.
The extension adds `predictionAttrsUrl` so every edited GeoPackage has the exact
sidecar the map must render with it.

```python
class EditedPredictionVersion(BaseModel):
    version: int
    gpkgUrl: str
    predictionAttrsUrl: Optional[str]
    createdAt: str
    createdBy: Optional[str]
    threshold: Optional[float]
    unknownThreshold: Optional[float]
    editedCount: int
    sourceGpkgUrl: Optional[str]
```

Serialized example:

```json
{
  "editedPredictions": [
    {
      "version": 1,
      "gpkgUrl": "https://storage/.../edited_predictions_5553_v1.gpkg",
      "predictionAttrsUrl": "https://storage/.../prediction_attrs_5553_v1.json",
      "createdAt": "2026-08-25T17:00:00Z",
      "createdBy": "analyst@example.com",
      "threshold": 0.1,
      "unknownThreshold": 0.0,
      "editedCount": 53,
      "sourceGpkgUrl": "https://storage/.../raw_predictions.gpkg"
    }
  ]
}
```

The schema now records the GeoPackage, sidecar URL, and provenance fields on
the same embedded object (`hastelib/src/hastegeo/core/models/projects.py:343-389`).
Keeping both URLs together prevents a sidecar generated later, by a different
path, from silently disagreeing with the saved GeoPackage.

### Modified Document Schema

| Container | Field | Before | After | Notes |
|---|---|---|---|---|
| Model metadata | `gpkgUrl` | optional string holding the prediction GeoPackage URL | unchanged | Always the raw producer output; editing must not overwrite it (`api/hastefuncapi/function_app.py:3202-3204`). |
| Model metadata | `predictionAttrsUrl` | raw/model-scoped sidecar URL | unchanged | Describes raw predictions only; the artifact template is `prediction_attrs_${modelId}` (`hastelib/src/hastegeo/core/config.py:172`, `hastelib/src/hastegeo/core/models/projects.py:529-535`). |
| Model metadata | `editedPredictions[].gpkgUrl` | edited GeoPackage URL | unchanged | The durable analyst-edited GeoPackage (`api/hastefuncapi/function_app.py:3311-3319`). |
| Model metadata | `editedPredictions[].predictionAttrsUrl` | absent | optional string URL to `prediction_attrs_${modelId}_v${version}` | Required before that version can be selected on the map; backfill may populate it for existing versions. |
| Model metadata | `editedPredictions` | optional list | append-only list | No mutable `activeEditedPredictionVersion` pointer is added. |

### Transport-Only Wire Models

`EditedPredictionsRequest` stays the save request body. It does not carry a
sidecar payload. The API builds the edited GeoPackage, calls the shared sidecar
builder, stores both artifacts, and only then appends the version metadata.

`PreparePredictionTilesRequest` gains a backfill mode for existing edited
versions. The mode is idempotent: it reads `Model.editedPredictions`, skips any
entry already carrying a valid `predictionAttrsUrl`, and writes only missing
`prediction_attrs_${modelId}_v${version}` sidecars.

---

## Blob Storage Changes

### New Containers

No new blob container. Use the existing artifact storage container and project
partitioning used by `ArtifactProcessor`.

| Container | Access Level | Naming Convention | Content Type |
|---|---|---|---|
| existing artifacts container | private | existing project/model namespace | GeoPackage / PMTiles / JSON |

### Modified Containers

| Container | Change | Description |
|---|---|---|
| existing artifacts container | add edited prediction GeoPackage blobs | One immutable-by-convention blob per numbered edit version. |
| existing artifacts container | add raw prediction attribute sidecar blobs | `prediction_attrs_${modelId}` describes raw predictions. |
| existing artifacts container | add versioned prediction attribute sidecar blobs | `prediction_attrs_${modelId}_v${version}` describes one edited GeoPackage. |
| existing artifacts container | add layer footprint PMTiles blobs | Shared geometry archive for all raw and edited versions on an image layer. |

### Blob Path Conventions

Artifact names are defined in `ArtifactTypes`; the current raw sidecar template
is model-scoped (`hastelib/src/hastegeo/core/config.py:168-180`). Add a separate
versioned sidecar artifact name rather than changing raw sidecar semantics.

```python
EDITED_PREDICTIONS_GPKG = Template("edited_predictions_${modelId}_v${version}")
PREDICTION_ATTRS = Template("prediction_attrs_${modelId}")
PREDICTION_ATTRS_VERSION = Template("prediction_attrs_${modelId}_v${version}")
LAYER_FOOTPRINT_PMTILES = Template("footprints_${imageLayerId}")
```

Logical layout:

```text
{artifact-container}/
  {projectId}/
    {modelId}/
      raw_predictions.gpkg
      prediction_attrs_{modelId}.json
      edited_predictions_{modelId}_v1.gpkg
      prediction_attrs_{modelId}_v1.json
      edited_predictions_{modelId}_v2.gpkg
      prediction_attrs_{modelId}_v2.json
    {imageLayerId}/
      footprints_{imageLayerId}.pmtiles
```

The physical namespace still follows `ArtifactProcessor`. The invariant is that
one edited GeoPackage version and its sidecar are derived from the same edited
rows and are advertised together or not at all.

#### Edited prediction GeoPackage schema

The source schemas differ by producer, but edited versions keep the same minimum
columns and row order. Edits rewrite `damaged` and `edited_class` but preserve
`damage_pct_0m`; that preserved fraction is why Assessment counts remain a
known out-of-scope semantic gap.

| Column | Type | Required | Description |
|---|---|---|---|
| `id` | int | yes | Source row index; must remain in original order. |
| `damage_pct_0m` | float | yes | Preserved producer damage fraction; not rewritten for manual overrides. |
| `unknown_pct` | float | yes | Unknown fraction; default to `0.0` when absent. |
| `damaged` | int | yes | Rewritten to `1` only when final class is `Damaged`. |
| `edited_class` | string | yes | `Damaged`, `NotDamaged`, or `Unknown` after overrides and thresholds. |
| `edit_threshold` | float | yes | Threshold used for this save. |
| `overture_id` | string | yes | Source footprint id copied by row order. |
| `geometry` | geometry | yes | Original prediction geometry and CRS. |

#### Attribute sidecar schema

The prediction attribute sidecar is JSON streamed by
`GetModelArtifact?kind=prediction_attrs` as `application/json`. Raw and edited
sidecars share the same schema.

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

All arrays must have length `n` and match the GeoPackage row order. The shared
builder now validates these invariants in `hastegeo.core.utils`, and the workflow
imports it so save-time generation and queue backfill use the same code
(`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`,
`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:77-92`).

---

## Data Lake Changes

### New Filesystems / Paths

No Data Lake filesystem changes are required. Edited GeoPackages and sidecars
are Blob artifacts only.

| Filesystem | Path Pattern | Data Format | Description |
|---|---|---|---|
| — | — | — | No Data Lake change. |

---

## Queue Storage Changes

### New Queues

No additional queue beyond the existing prediction-edit prep queue. The queue
message gains a backfill mode.

| Queue Name | Message Schema | Producer | Consumer |
|---|---|---|---|
| `prediction-edit-prep-queue` | Existing prep fields plus `backfillVersions` | `PutPreparePredictionTilesQueueMessage` or maintenance/backfill call | `hastefuncqueues` prediction-edit-prep trigger |

Backfill mode is for historical edited versions only. Normal save-time sidecar
creation happens synchronously with `PutEditedPredictions`; lazy sidecar
creation during `GetVisualizerResults` is not allowed.

---

## Azure Batch Changes

### Pool Configuration

| Setting | Value | Notes |
|---|---|---|
| VM SKU | existing training/CPU-capable pool | No GPU requirement. |
| Pool size | existing autoscale | Backfill is bounded and idempotent. |
| Container image | `docker/training/` | Prep still runs where existing geospatial tooling is installed. |

---

## Data Flow

### Write Path

Edit save path:

```text
Visualizer save overrides + thresholds
  → hastefuncapi PutEditedPredictions
  → apply edits to raw GeoPackage
  → write edited_predictions_{modelId}_v{version}.gpkg
  → build prediction_attrs_{modelId}_v{version}.json from the edited GeoPackage
  → store both blobs
  → append EditedPredictionVersion {version, gpkgUrl, predictionAttrsUrl, ...}
```

The sidecar is derived data, but it must be written in the same call path as its
GeoPackage. If sidecar generation or upload fails, the version must not be shown
as selectable because the map could otherwise draw classes from a different
artifact.

Prep/backfill path:

```text
Operator or deployment task requests prediction-tile backfill
  → prediction-edit-prep-queue message with backfillVersions=true
  → worker loads Model.editedPredictions
  → for each version lacking predictionAttrsUrl, build sidecar from gpkgUrl
  → skip versions that already have sidecars unless force=true
  → save only the newly populated version metadata
```

Read path:

```text
UI selects raw / v1 / v2 on View Results
  → GetVisualizerResults?version=N
  → response carries selected predictionAttrsUrl and isNewestPredictionVersion
  → UI fetches footprint_pmtiles and prediction_attrs through GetModelArtifact
  → both swipe panes replace their sidecar/class state together
```

Report path:

```text
Validation / Assessment report buttons
  → GetValidationReport or GetAssessmentReport without the map selector version
  → backend resolves newest edited version by default
```

This intentionally allows the map to show v2 while reports reflect v3. The UI
must disclose that consequence.

---

## Migration Plan

### Forward Migration

1. Deploy the extended `EditedPredictionVersion` schema and versioned sidecar
   artifact template.
2. Move shared sidecar generation into `hastegeo.core.utils` and update the
   workflow to import it.
3. Update `PutEditedPredictions` to write edited GeoPackage and sidecar together.
4. Update `GetModelArtifact` and `GetVisualizerResults` to resolve raw vs edited
   sidecars by `version`.
5. Deploy UI selector, warning copy, disabled missing-sidecar state, and download
   buttons.
6. Run backfill for existing edited versions. Dev currently has two known
   targets: model `0448` v1 and model `5553` v1.
7. Verify no selectable version lacks `predictionAttrsUrl` before broad rollout.

The backfill creates a temporary window where pre-existing versions cannot be
selected. The selector must show those rows disabled with explanatory text
instead of rendering an empty map.

### Backward Migration

1. Revert UI selector/download deployment if the map-selection workflow must be
   hidden.
2. Revert API changes if versioned artifact resolution regresses.
3. Leave `editedPredictions[].predictionAttrsUrl` in Cosmos; older code ignores
   the unknown optional field.
4. Leave versioned sidecar blobs in storage unless approved cleanup tooling is
   run.
5. Use `version=0` for raw reports and omit `version` for newest-edited reports
   while rollback is evaluated.

## Data Volume Estimates

| Entity / Container | Initial Size | Growth Rate | Retention |
|---|---|---|---|
| `Model.editedPredictions` list | 0-20 small objects per model | one entry per save | same as model metadata |
| Edited GeoPackage blobs | roughly source prediction GPKG size per version | one blob per save | same as project artifacts |
| Raw prediction sidecar | one compact JSON array set per model | regenerated when raw predictions change | replaceable derived cache |
| Versioned prediction sidecar | one compact JSON array set per edited version | one per save plus one-time backfill | same as edited version unless cleanup approved |
| Footprint PMTiles | one geometry-only archive per image layer | generated once per layer | replaceable derived cache |

## Caching Strategy

| Data | Cache Layer | TTL | Invalidation |
|---|---|---|---|
| `GetVisualizerResults` payload | Browser route state | current View Results load | Refetch when selector changes or route changes. |
| `prediction_attrs` sidecar | Browser memory keyed by selected version | current visualizer session | Refetch when `predictionAttrsUrl` or selected version changes. |
| `footprint_pmtiles` | Browser memory / HTTP cache | current visualizer session | Shared across versions for the same layer. |
| Edited version list | Browser state | current visualizer session | Refresh after save and after backfill/polling detects new sidecar URLs. |
| Disabled version state | Browser state from metadata | current visualizer session | Re-evaluate after backfill completes. |
