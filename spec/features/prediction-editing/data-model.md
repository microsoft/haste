# Data Model: Prediction Editing

**Contents:** [Cosmos DB Changes](#cosmos-db-changes) · [Blob Storage Changes](#blob-storage-changes) · [Data Lake Changes](#data-lake-changes) · [Queue Storage Changes](#queue-storage-changes) · [Azure Batch Changes](#azure-batch-changes) · [Data Flow](#data-flow) · [Migration Plan](#migration-plan) · [Data Volume Estimates](#data-volume-estimates) · [Caching Strategy](#caching-strategy)

## Cosmos DB Changes

### New Containers

No new Cosmos containers. Prediction edit metadata is embedded in the existing
Model and ImageLayer metadata documents so reads remain local to the project.

| Container | Partition Key | Description |
|---|---|---|
| — | — | No new container. |

### Modified Containers

| Container | Change | Migration Needed? |
|---|---|---|
| Model metadata | Add `editedPredictions`, `predictedBuildingCount`, `predictedAt`, `predictionAttrsUrl`, `predictionTilesJob`, `predictionTilesStatus`, and `predictionTilesStatusMessage` | no — nullable/defaulted fields are backward-compatible |
| ImageLayer metadata | Add `footprintPmtilesUrl` | no — nullable/defaulted field is backward-compatible |

### New Document Schema

**Container:** existing Model metadata document  
**Partition key:** `projectId`

`EditedPredictionVersion` is embedded as a list entry on `Model`:

```python
class EditedPredictionVersion(BaseModel):
    version: int
    gpkgUrl: str
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
      "gpkgUrl": "https://storage/.../edited_predictions_12345_v1.gpkg",
      "createdAt": "2026-08-21T05:10:48Z",
      "createdBy": "analyst@example.com",
      "threshold": 0.1,
      "unknownThreshold": 0.0,
      "editedCount": 53,
      "sourceGpkgUrl": "https://storage/.../raw_predictions.gpkg"
    }
  ]
}
```

**RU estimate:** One point read of the Model, one point read of the ImageLayer,
and one Model upsert per save. The embedded list is expected to be small; if
version history grows beyond Cosmos document limits, promote it to a dedicated
registry in a follow-up ADR.

### Modified Document Schema

| Container | Field | Before | After | Notes |
|---|---|---|---|---|
| Model metadata | `gpkgUrl` | optional string holding the prediction GeoPackage url | unchanged | Remains the raw prediction pointer; writing edited versions here would clobber the source (`hastelib/src/hastegeo/core/models/projects.py:440`). |
| Model metadata | `editedPredictions` | absent | `Optional[List[EditedPredictionVersion]]`, default empty list | Append-only numbered history: `edit_v1`, `edit_v2`, … |
| Model metadata | `predictedBuildingCount` | absent | `Optional[int]` | Positive count gates embedding editing; avoids treating an empty prediction write as editable. |
| Model metadata | `predictedAt` | absent | `Optional[str]` ISO 8601 timestamp | Set when embedding predictions are written or prep validates the raw prediction set. |
| Model metadata | `predictionAttrsUrl` | absent | `Optional[str]` | URL to the per-model columnar prediction attribute JSON sidecar. |
| Model metadata | `predictionTilesJob` | absent | `Optional[TrainingJob]` | Batch/local runner job metadata for the queued prep workflow. |
| Model metadata | `predictionTilesStatus` | absent | `Optional[str]` | Prep status using HASTE status values: `Queued`, `InProgress`, `Processed`, `Failed`, `Cancelled`. |
| Model metadata | `predictionTilesStatusMessage` | absent | `Optional[str]`, default `""` | User-visible appended progress/failure messages for prep polling. |
| ImageLayer metadata | `footprintPmtilesUrl` | absent | `Optional[str]` | Layer-level PMTiles for all footprints used by prediction editing. |

### Transport-Only Wire Models

`PredictionOverrideRequest`, `EditedPredictionsRequest`, and
`PreparePredictionTilesRequest` live in
`hastelib/src/hastegeo/core/models/predictions.py`. They validate HTTP request
bodies for `PutEditedPredictions` and `PutPreparePredictionTilesQueueMessage`
but are not persisted in Cosmos DB.

They deliberately do not live in `function_app.py`, which remains a thin HTTP
wrapper, or in `projects.py`, which holds persisted document schemas. This
mirrors the publishing split between `PublishRequest` transport models and the
persisted `PublishedDataset` schema in `publishing.py`.

`store_artifact` currently uploads with `overwrite=True`, so version identity
comes from unique artifact names instead of mutating a blob in place
(`hastelib/src/hastegeo/core/artifact_storage/azure_blob_artifact_storage.py:255`).

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
| existing artifacts container | add edited prediction GeoPackage blobs | One immutable blob per numbered edit version. |
| existing artifacts container | add prediction attribute sidecar blobs | Columnar JSON sidecar for full prediction attributes. |
| existing artifacts container | add layer footprint PMTiles blobs | Layer-level PMTiles shared by models for an image layer. |

### Blob Path Conventions

Artifact names are added to `ArtifactTypes`:

```python
EDITED_PREDICTIONS_GPKG = Template("edited_predictions_${modelId}_v${version}")
PREDICTION_ATTRS        = Template("prediction_attrs_${modelId}")
LAYER_FOOTPRINT_PMTILES = Template("footprints_${imageLayerId}")
```

Logical layout:

```text
{artifact-container}/
  {projectId}/
    {modelId}/
      edited_predictions_{modelId}_v1.gpkg
      edited_predictions_{modelId}_v2.gpkg
      prediction_attrs_{modelId}.json
    {imageLayerId}/
      footprints_{imageLayerId}.pmtiles
```

The exact physical namespace should follow `ArtifactProcessor` conventions, but
artifact names must match the templates above. Edited GeoPackages are immutable
by convention; a later save always writes the next version.

#### Edited prediction GeoPackage schema

The source schemas differ by producer. Trained inference writes continuous
fractions and a default layer name; embedding writes layer `"predictions"`, an
`area` column, and `damage_pct_0m` as a 0.0/1.0 copy of `damaged`
(`docker/training/code/merge_with_building_footprints.py:221-231`,
`api/hastefuncapi/function_app.py:2638-2786`). The edited output must normalize
the minimum columns below while preserving any safe source columns that do not
conflict.

| Column | Type | Required | Description |
|---|---|---|---|
| `id` | int | yes | Source row index; must remain in original order. |
| `damage_pct_0m` | float | yes | Damage fraction in `[0,1]`; continuous for trained inference, degenerate 0.0/1.0 for embedding. |
| `damage_pct_10m` | float | trained source only | Preserve when present. |
| `damage_pct_20m` | float | trained source only | Preserve when present. |
| `unknown_pct` | float | yes | Unknown fraction; default to `0.0` when absent. |
| `damaged` | int | yes | Rewritten to `1` only when final class is `Damaged`; otherwise `0`. |
| `area` | float | embedding source only | Preserve when present. |
| `edited_class` | string | yes | `Damaged`, `NotDamaged`, or `Unknown` after overrides and thresholds. |
| `edit_threshold` | float | yes | Threshold used for this save; still written for embedding for provenance. |
| `overture_id` | string | yes | Explicit Overture building id copied from source footprints by row order. |
| `geometry` | geometry | yes | Original prediction geometry and CRS. |

The existing trained output computes `damaged` as `damage_pct_0m > 0`
(`docker/training/code/merge_with_building_footprints.py:254`). Edited outputs
replace that rule with the documented thresholded final class.

#### Attribute sidecar schema

The prediction attribute sidecar is JSON and is streamed by
`GetModelArtifact?kind=prediction_attrs` as `application/json`:

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

All arrays must have length `n` and must be ordered exactly like the prediction
GeoPackage rows. This order matters because current report logic joins
predictions to Overture ids positionally, not by id
(`hastelib/src/hastegeo/core/utils/assessment.py:376-395`,
`api/hastefuncapi/function_app.py:4116-4133`).

---

## Data Lake Changes

### New Filesystems / Paths

No Data Lake filesystem changes are required for v1. Edited versions are Blob
artifacts only.

| Filesystem | Path Pattern | Data Format | Description |
|---|---|---|---|
| — | — | — | No Data Lake change. |

---

## Queue Storage Changes

### New Queues

| Queue Name | Message Schema | Producer | Consumer |
|---|---|---|---|
| `prediction-edit-prep-queue` | See [design.md](design.md#queue-prediction-edit-prep-queue) | `hastefuncapi` `PutPreparePredictionTilesQueueMessage` | `hastefuncqueues` prediction-edit-prep trigger |

The queue is for PMTiles and sidecar preparation only. Saving edited
GeoPackages remains an API-driven write in v1.

`infra/modules/functions.bicep` does not add explicit app-setting parity for
this queue in the current implementation. `Config` supplies the
`prediction-edit-prep-queue` default, the Functions host can create the queue,
and editing Bicep without regenerating `infra/main.json` would create infra
drift.

---

## Azure Batch Changes

### Pool Configuration

| Setting | Value | Notes |
|---|---|---|
| VM SKU | existing training/CPU-capable pool | No GPU requirement; uses the training image because it includes `tippecanoe`. |
| Pool size | existing autoscale | Prep is bursty and should not require a dedicated pool in v1. |
| Container image | `docker/training/` | `tippecanoe` is present only in the training conda env (`docker/training/env/env.yml:11`). |

---

## Data Flow

### Write Path

```text
UI save overrides + thresholds
  → hastefuncapi PutEditedPredictions
  → hastegeo.core.processors.prediction_edits.apply_edits
  → hastegeo.core.processors.prediction_edits.store_edited_version
  → Blob Storage edited_predictions_{modelId}_v{version}.gpkg
  → Cosmos Model.editedPredictions append
```

Prep write path:

```text
UI opens editor
  → hastefuncapi GetPredictionEditSession
  → hastefuncapi PutPreparePredictionTilesQueueMessage when missing
  → Queue Storage prediction-edit-prep-queue
  → hastefuncqueues
  → training image workflow builds PMTiles + sidecar
  → Blob Storage footprints_{imageLayerId}.pmtiles + prediction_attrs_{modelId}.json
  → Cosmos ImageLayer.footprintPmtilesUrl + Model.predictionAttrsUrl/predictedBuildingCount/predictedAt/predictionTilesStatus
```

### Read Path

```text
UI PredictionEditor page
  → hastefuncapi GetPredictionEditSession (metadata and readiness)
  → hastefuncapi GetModelArtifact?kind=footprint_pmtiles
  → hastefuncapi GetModelArtifact?kind=prediction_attrs
  → Azure Maps PMTiles + in-memory sidecar rendering
  → hastefuncapi GetEditedPredictionVersions (history)
```

---

## Migration Plan

### Forward Migration

1. Deploy Pydantic schema changes with nullable/defaulted fields.
2. Deploy new artifact types and `GetModelArtifact` kinds.
3. Deploy queue worker support for PMTiles and sidecar creation.
4. Deploy API routes and the explicit prep PUT route.
5. Deploy UI route and edit buttons.
6. Enable the feature in dev/test and backfill `predictedBuildingCount` through
   `PutBuildingPredictions` for embedding models or prep completion for raw
   prediction GeoPackages.

Existing trained models can use `inferenceStatus === "Processed" && gpkgUrl`.
Existing embedding models with only `gpkgUrl` should remain disabled until a
positive `predictedBuildingCount` is set, because `PutBuildingPredictions` can
write empty predictions while still setting `gpkgUrl`
(`api/hastefuncapi/function_app.py:2638-2786`,
`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:86`).

### Backward Migration

1. Revert API and UI deployments if needed.
2. Stop or drain the prediction-edit prep queue if workers are failing.
3. Leave `editedPredictions`, `predictedBuildingCount`, `predictedAt`,
   `predictionAttrsUrl`, `predictionTilesJob`, `predictionTilesStatus`,
   `predictionTilesStatusMessage`, and `footprintPmtilesUrl` fields in place;
   old code ignores unknown optional fields.
4. Leave edited GeoPackage, PMTiles, and sidecar blobs in storage unless a
   cleanup script is explicitly approved.

## Data Volume Estimates

| Entity / Container | Initial Size | Growth Rate | Retention |
|---|---|---|---|
| `Model.editedPredictions` list | 0-20 small objects per model | one entry per save | same as model metadata |
| Edited GeoPackage blobs | roughly source prediction GPKG size per version | one blob per save | same as project artifacts |
| Prediction attribute sidecar | one compact JSON array set per model | regenerated when source predictions change | replaceable derived cache |
| Footprint PMTiles | one geometry-only archive per image layer | generated once per layer | replaceable derived cache |

## Caching Strategy

| Data | Cache Layer | TTL | Invalidation |
|---|---|---|---|
| `GetPredictionEditSession` metadata | Browser state | until model refresh or route leave | Reload after save or prep completion. |
| `prediction_attrs` sidecar | Browser memory | current editor session | Refetch when `predictedAt` or source `gpkgUrl` changes. |
| `footprint_pmtiles` | Browser memory / HTTP cache | current editor session; cacheable by blob version/url | Regenerate when source footprints change. |
| Edited version list | Browser state | current editor session | Refresh after `PutEditedPredictions` succeeds. |
