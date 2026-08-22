# ADR-0005: Introduce Versioned Derived Prediction Artifacts

**Status:** proposed
**Date:** 2026-08-21
**Deciders:** HASTE engineering team

**Contents:** [Context](#context) · [Options Considered](#options-considered) · [Decision](#decision) · [Consequences](#consequences)

## Context

Prediction editing needs analysts to save corrected building-level prediction
outputs without losing the raw model result. HASTE's raw prediction pointer is
`Model.gpkgUrl`; overwriting that pointer or blob would remove the provenance
needed to compare model output with analyst edits and would be especially risky
because artifact writes can overwrite same-named blobs in the storage layer.

The implemented prediction-editing design writes edited GeoPackages as derived
artifacts and records a numbered metadata entry for each save. The raw
`Model.gpkgUrl` remains the producer output. There is no stored mutable
"current edited version" pointer. Instead, readers that support edited versions
call `resolve_prediction_source(model, version=None)`: omitted `version` resolves
to the newest edited artifact when one exists, `version=0` forces the raw output,
and an explicit positive version resolves that exact edited artifact
(`hastelib/src/hastegeo/core/utils/predictions.py:332-401`).

That resolver is now used by `GetVisualizerResults`, `GetValidationReport`, and
`GetAssessmentReport`, each with an optional `version` query parameter. The
visualizer payload reports which version is on the map and lists available
versions, but the current UI version history is read-only: choosing an older
version in the panel does not refetch the map yet
(`api/hastefuncapi/function_app.py:2296-2435`,
`api/hastefuncapi/function_app.py:4607-4688`,
`api/hastefuncapi/function_app.py:4929-5027`,
`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`).

## Options Considered

### Option A: Overwrite `Model.gpkgUrl` in place

- **Pros:** Smallest data-model change; all current consumers would immediately
  see analyst edits without new parameters.
- **Cons:** Destroys the raw model output, loses auditability, makes it hard to
  compare model vs analyst decisions, and is unsafe because artifact storage can
  overwrite same-named blobs.
- **Impact on HASTE components:** Minimal code change, but high behavioral risk
  across reports, validation, publishing, downloads, and visualizer rendering.

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
  history, uses unique blob artifact names, avoids new containers, and lets
  readers select raw/newest/explicit versions without a mutable active pointer.
- **Cons:** Model documents grow with each save; version history is scoped to
  prediction editing rather than a reusable artifact registry; the current
  implementation does not yet protect concurrent saves when assigning the next
  number.
- **Impact on HASTE components:** Adds optional Model fields, new artifact-type
  templates, API additions, a source resolver, report/visualizer version
  support, and UI version-list rendering.

### Option E: Store an `activeEditedPredictionVersion` pointer

- **Pros:** Lets users switch the default edited version without changing every
  reader URL.
- **Cons:** Introduces mutable global state on the Model document; report and
  visualizer results could change after a pointer update even when callers did
  not ask for a different artifact; races and audit semantics become harder.
- **Impact on HASTE components:** Requires write APIs and UI for switching the
  active pointer, plus stronger concurrency controls. This is not implemented.

## Decision

Adopt **Option D: a numbered edited-version list on the Model document** and
reject a mutable active-version pointer.

Each prediction-edit save writes a new immutable-by-convention blob named from
`EDITED_PREDICTIONS_GPKG = Template("edited_predictions_${modelId}_v${version}")`
and appends one `EditedPredictionVersion` entry to `Model.editedPredictions`.
The displayed version names are `edit_v1`, `edit_v2`, and so on, derived from
the numeric `version` field. The raw prediction remains in `Model.gpkgUrl` and
must not be mutated by the edit flow.

`EditedPredictionVersion` stores `version`, `gpkgUrl`, `createdAt`, `createdBy`,
`threshold`, `unknownThreshold`, `editedCount`, and `sourceGpkgUrl`. The API
allocates the next version from the current Model document, writes the blob under
that versioned artifact name, and appends metadata. The implemented v1 does
**not** include the proposed 409 conflict response for simultaneous saves:
`next_version` plus metadata save is currently a read-modify-write without
optimistic concurrency, so a follow-up must add ETag, lease, or retry-safe
allocation before multi-analyst collision safety is guaranteed.

Readers use `resolve_prediction_source` rather than a persisted active pointer.
By default, `GetVisualizerResults`, `GetValidationReport`, and
`GetAssessmentReport` use the newest edited version when one exists. Callers can
request `version=0` for the raw model output or `version=N` for an explicit
edited artifact; the public API contract documents these query parameters and
the visualizer response fields (`docs/api/hastefuncapi.md:78-157`,
`docs/api/hastefuncapi.md:480-502`).

The separate `PutPreparePredictionTilesQueueMessage` route affects only PMTiles
and prediction-attribute preparation; it does not change this artifact-versioning
decision. PMTiles and sidecars are derived artifacts used by the vector-first
results viewer, while edited GeoPackage versions remain the durable analyst
outputs.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Model metadata | `hastelib/src/hastegeo/core/models/projects.py` | Add `EditedPredictionVersion` and `Model.editedPredictions`; preserve raw `gpkgUrl`. |
| Artifact naming | `hastelib/src/hastegeo/core/config.py` | Add `EDITED_PREDICTIONS_GPKG` and prediction prep artifact templates. |
| Prediction editing processor | `hastelib/src/hastegeo/core/processors/prediction_edits.py` | Allocate versions, write edited GeoPackages, and append metadata. |
| Prediction source resolver | `hastelib/src/hastegeo/core/utils/predictions.py` | Resolve newest edited, raw, or explicit edited source without a mutable pointer. |
| REST API | `api/hastefuncapi/function_app.py` | Add save/list/prep endpoints; update visualizer, validation, and assessment readers to accept `version`. |
| React UI | `ui/src/Components/Visualizer/` | Render vector-first results and edit mode on the existing Visualizer page; show read-only version history. |

### Azure Services Affected

| Service | Change |
|---|---|
| Cosmos DB | Existing Model documents gain an optional embedded version list and optional prep/readiness metadata. |
| Blob Storage | Stores one edited GeoPackage blob per version plus PMTiles and sidecar derived artifacts. |
| Azure Functions | New HTTP save/list/prep operations read and update Model metadata; existing visualizer/report operations resolve versions. |
| Azure Queue / Batch | Prep messages and jobs generate PMTiles and prediction attribute sidecars; edited versioning itself remains HTTP + Blob/Cosmos. |

## Consequences

- **Easier:** Analysts can save multiple reviewed outputs; engineers can reason
  about raw vs edited provenance; rollback does not require restoring raw blobs;
  visualizer, validation, and assessment callers can choose raw/newest/explicit
  sources with the same `version` contract.
- **Harder:** A Model document can grow over time, concurrent saves still need
  protection around version allocation, and the UI does not yet provide wired
  version switching even though the payload lists available versions.
- **New constraints:** The edit flow must never write edited data to
  `Model.gpkgUrl`; every edited artifact name must include the assigned version;
  source selection must go through `resolve_prediction_source`; readers must use
  `version=0` when they need the raw producer output.
- **Known semantic gap:** `GetValidationReport` reads edited `damaged`, so edits
  move its metrics. `GetAssessmentReport` opens the selected GeoPackage but
  still thresholds the producer's preserved `damage_pct_0m`, so per-building
  overrides do not move assessment counts until a follow-up decision changes the
  assessment contract.
- **Impact on Docker Compose local dev stack:** No new storage service; local
  Azurite must hold additional edited GeoPackage blobs, PMTiles, and sidecars.
- **Impact on CI/CD workflows:** No workflow change expected unless additional
  automated test jobs are added later.
