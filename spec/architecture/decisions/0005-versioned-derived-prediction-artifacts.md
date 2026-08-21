# ADR-0005: Introduce Versioned Derived Prediction Artifacts

**Status:** proposed
**Date:** 2026-08-21
**Deciders:** HASTE engineering team

**Contents:** [Context](#context) · [Options Considered](#options-considered) · [Decision](#decision) · [Consequences](#consequences)

## Context

Prediction editing needs analysts to save corrected building-level prediction
outputs without losing the raw model result. HASTE does not currently have
artifact versioning: blob writes through `store_artifact` use `overwrite=True`,
and `Model.gpkgUrl` is the single pointer to the raw prediction GeoPackage
(`hastelib/src/hastegeo/core/artifact_storage/azure_blob_artifact_storage.py:255`,
`hastelib/src/hastegeo/core/models/projects.py:440`). Overwriting that pointer
or blob would remove the provenance needed to compare model output with analyst
edits.

The feature spec at `spec/features/prediction-editing/` introduces edited
prediction GeoPackages as derived artifacts. Each save must produce a new
version (`edit_v1`, `edit_v2`, …) that is listable and downloadable, while
assessment reports, validation reports, publishing, and the visualizer continue
to read the raw model output until later specs opt in.

## Options Considered

### Option A: Overwrite `Model.gpkgUrl` in place

- **Pros:** Smallest data-model change; all current consumers would immediately
  see analyst edits without new parameters.
- **Cons:** Destroys the raw model output, loses auditability, makes it hard to
  compare model vs analyst decisions, and is unsafe because artifact storage
  already overwrites same-named blobs.
- **Impact on HASTE components:** Minimal code change, but high behavioral risk
  across reports, validation, publishing, and downloads.

### Option B: Use Azure Blob snapshots for edited outputs

- **Pros:** Keeps physical versions close to the source blob; relies on Azure
  Storage features rather than new metadata structures.
- **Cons:** Couples HASTE semantics to one storage backend, snapshots are not a
  clear user-facing version history, SAS/download flows become harder to reason
  about, and the metadata store still needs to know which snapshot is an edited
  prediction.
- **Impact on HASTE components:** Requires storage-layer snapshot support and
  new API logic to list and authorize snapshots; weak fit for local/Azurite and
  any future non-Blob artifact storage.

### Option C: Introduce a generic artifact registry

- **Pros:** Solves versioning for all artifact types, can model provenance and
  lifecycle uniformly, and could support future publishing/report selection.
- **Cons:** Large architecture change for a focused editing feature; requires
  new metadata schemas, migrations, APIs, UI patterns, and rollout planning
  beyond the current scope.
- **Impact on HASTE components:** Broad changes across `hastelib`, API, UI,
  storage, and downstream consumers; higher schedule and migration risk.

### Option D: Store a numbered edited-version list on the Model document (Chosen)

- **Pros:** Preserves raw `Model.gpkgUrl`, gives analysts a simple version
  history, uses unique blob artifact names, avoids new containers, and keeps
  downstream consumers unchanged in v1.
- **Cons:** Model documents grow with each save; version history is scoped to
  prediction editing rather than a reusable artifact registry; the current
  implementation does not yet protect concurrent saves when assigning the next
  number.
- **Impact on HASTE components:** Adds optional Model fields, new artifact-type
  templates, small API additions, and UI version-list rendering.

## Decision

Adopt **Option D: a numbered edited-version list on the Model document**.

Each prediction-edit save writes a new immutable-by-convention blob named from
`EDITED_PREDICTIONS_GPKG = Template("edited_predictions_${modelId}_v${version}")`
and appends one `EditedPredictionVersion` entry to `Model.editedPredictions`.
The displayed version names are `edit_v1`, `edit_v2`, and so on, derived from
the numeric `version` field. The raw prediction remains in `Model.gpkgUrl` and
must not be mutated by the edit flow.

`EditedPredictionVersion` stores `version`, `gpkgUrl`, `createdAt`, `createdBy`,
`threshold`, `unknownThreshold`, `editedCount`, and `sourceGpkgUrl`. The API
allocates the next version from the current Model document, writes the blob under
that versioned artifact name, and appends metadata. Existing downstream
consumers continue to use the raw prediction pointer unless a future ADR/spec
introduces active-version selection.

The implemented v1 does **not** include the proposed 409 conflict response for
simultaneous saves. `next_version` plus metadata save is currently a
read-modify-write without optimistic concurrency, so a follow-up must add ETag,
lease, or retry-safe allocation before multi-analyst collision safety is
guaranteed. The separate `PutPreparePredictionTilesQueueMessage` route affects
only PMTiles/attribute preparation; it does not change this artifact-versioning
decision.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Model metadata | `hastelib/src/hastegeo/core/models/projects.py` | Add `EditedPredictionVersion` and `Model.editedPredictions`; preserve raw `gpkgUrl`. |
| Artifact naming | `hastelib/src/hastegeo/core/config.py` | Add `EDITED_PREDICTIONS_GPKG` template. |
| Prediction editing processor | `hastelib/src/hastegeo/core/processors/prediction_edits.py` | Allocate versions, write edited GeoPackages, and append metadata. |
| REST API | `api/hastefuncapi/function_app.py` | Add save/list endpoints that expose edited versions without changing existing report endpoints. |
| React UI | `ui/src/Components/PredictionEditor/` | Show version history in the editor. |

### Azure Services Affected

| Service | Change |
|---|---|
| Cosmos DB | Existing Model documents gain an optional embedded version list. |
| Blob Storage | Stores one edited GeoPackage blob per version. |
| Azure Functions | New HTTP save/list operations read and update Model metadata. |

## Consequences

- **Easier:** Analysts can save multiple reviewed outputs; engineers can reason
  about raw vs edited provenance; rollback does not require restoring raw blobs.
- **Harder:** A Model document can grow over time, and concurrent saves still
  need protection around version allocation.
- **New constraints:** The edit flow must never write edited data to
  `Model.gpkgUrl`; every edited artifact name must include the assigned version;
  downstream consumers need explicit future work before they can use edits.
- **Impact on Docker Compose local dev stack:** No new storage service; local
  Azurite must hold additional edited GeoPackage blobs.
- **Impact on CI/CD workflows:** No workflow change expected unless additional
  automated test jobs are added later.
