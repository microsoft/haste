# ADR-0005: Introduce Versioned Derived Prediction Artifacts

**Status:** proposed
**Date:** 2026-08-21
**Deciders:** HASTE engineering team

**Contents:** [Context](#context) · [Options Considered](#options-considered) · [Decision](#decision) · [Consequences](#consequences)

## Context

Prediction editing needs analysts to save corrected building-level prediction
outputs without losing the raw model result. HASTE's raw prediction pointer is
`Model.gpkgUrl`; overwriting that pointer or blob would remove provenance and
would be risky because artifact writes can overwrite same-named blobs.

The established design writes edited GeoPackages as derived artifacts and
records a numbered metadata entry for each save. The raw `Model.gpkgUrl` remains
the producer output. There is no stored mutable "current edited version" pointer;
readers resolve raw, newest, or explicit versions through the version contract
(`api/hastefuncapi/function_app.py:2307-2340`,
`api/hastefuncapi/function_app.py:2386-2397`).

The View Results map now needs to select and download individual versions. The
map does not read classes from the GeoPackage directly; it renders PMTiles
geometry colored by a compact prediction-attribute sidecar. That sidecar was
keyed per model, `prediction_attrs_${modelId}`, and described only raw
predictions (`hastelib/src/hastegeo/core/config.py:172`,
`hastelib/src/hastegeo/core/models/projects.py:529-535`). The current API save route writes a new edited GeoPackage and appends metadata,
but still needs to adopt the shared save helper that stores the matching sidecar
(`api/hastefuncapi/function_app.py:3302-3325`,
`hastelib/src/hastegeo/core/processors/prediction_edits.py:520-608`). Selecting an edited GPKG
without a matching sidecar would silently render raw classes.

The sidecar builder now lives in `hastegeo.core.utils.prediction_attrs`, and the
training-image workflow imports it (`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`,
`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:77-92`). This lets
the Functions app build the sidecar in the save path without importing workflow
code that belongs to tile preparation.

## Options Considered

### Option A: Overwrite `Model.gpkgUrl` in place

- **Pros:** Smallest data-model change; all consumers immediately see edits.
- **Cons:** Destroys raw output, loses auditability, and makes downloads/reports
  impossible to trace back to producer output.
- **Impact on HASTE components:** Minimal code change but high behavioral risk.

### Option B: Use Azure Blob snapshots for edited outputs

- **Pros:** Keeps physical versions near the source blob.
- **Cons:** Couples semantics to Blob snapshots, still needs user-facing
  metadata, and complicates authorization/download behavior.
- **Impact on HASTE components:** Storage-specific API and UI changes.

### Option C: Introduce a generic artifact registry

- **Pros:** Uniform lifecycle and provenance model for all artifacts.
- **Cons:** Large architecture change beyond prediction editing.
- **Impact on HASTE components:** Broad schema, API, migration, and UI work.

### Option D: Store a numbered edited-version list on the Model document (Chosen)

- **Pros:** Preserves raw `Model.gpkgUrl`, gives analysts a simple history, uses
  versioned artifact names, and avoids mutable active-version state.
- **Cons:** Model documents grow with each save, concurrent saves still need
  stronger version allocation, and sidecar consistency must be enforced.
- **Impact on HASTE components:** Adds Model fields, artifact templates, source
  resolution, visualizer/report version support, and UI version controls.

### Option E: Store an `activeEditedPredictionVersion` pointer

- **Pros:** Lets users switch a global default without passing query parameters.
- **Cons:** Introduces mutable global state; reports and maps could change after
  a pointer update even when callers did not ask for a different artifact.
- **Impact on HASTE components:** Requires write APIs, conflict handling, and
  more audit semantics. This remains rejected.

## Decision

Adopt **Option D: a numbered edited-version list on the Model document** and
reject a mutable active-version pointer. This ADR is amended to include
versioned sidecars as derived data for each edited version.

Each prediction-edit save writes a new GeoPackage named from
`EDITED_PREDICTIONS_GPKG = Template("edited_predictions_${modelId}_v${version}")`
and appends one `EditedPredictionVersion` entry. The raw prediction remains in
`Model.gpkgUrl` and must not be mutated by the edit flow (`api/hastefuncapi/function_app.py:3202-3204`).

Each saved version must also write a matching prediction-attribute sidecar named
`prediction_attrs_${modelId}_v${version}`. `EditedPredictionVersion` records the
sidecar URL next to `gpkgUrl`. The raw/model-scoped sidecar
`prediction_attrs_${modelId}` remains the raw-output sidecar. Sidecars are
derived artifacts, but a versioned sidecar must be written in the same call path
as its GeoPackage; if the sidecar cannot be generated or stored, the version must
not be advertised as selectable. Otherwise the map could show classes from one
artifact while downloads provide another.

Keep `build_prediction_attrs` and `write_prediction_attrs` in
`hastegeo.core.utils` so the Functions save path, queue prep, and backfill use
one implementation. The prediction-tiles workflow imports and re-exports those
helpers (`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`,
`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:77-92`).

`GetVisualizerResults` supports `version`: omitted selects newest edited (or raw
fallback), `version=0` selects raw, and positive `version=N` selects that saved
version. The response returns the selected version's `predictionAttrsUrl`, the
selected `predictionVersion`, and an `isNewestPredictionVersion` flag. Unknown
positive versions return 404 and malformed versions return 400.

Version selection changes **only the map**. Assessment and Validation report
buttons continue to omit the selector version and therefore use their existing
newest-edited default. The accepted trade-off is that the map can show v2 while
a report reflects v3; the UI must state this clearly instead of letting users
discover it (`api/hastefuncapi/function_app.py:4607-4688`,
`api/hastefuncapi/function_app.py:4929-5027`).

Downloads are exposed in two places: beside the View Results selector and on
each edit-panel version-history row. New version downloads route through
`GetModelArtifact` with `kind=gpkg&version=<selected>` rather than direct blob or
SAS URL rewriting, preserving existing auth, managed identity, Range, and
content-disposition handling (`api/hastefuncapi/function_app.py:1430-1570`,
`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:61-69`).

Pre-existing edited versions are backfilled once through the prediction-tiles job
instead of generated lazily on first selection. Backfill is idempotent and skips
versions that already have sidecars. Dev models `0448` v1 and `5553` v1 are the
known initial backfill targets.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Model metadata | `hastelib/src/hastegeo/core/models/projects.py` | Extend `EditedPredictionVersion` with `predictionAttrsUrl`; keep no active pointer. |
| Artifact naming | `hastelib/src/hastegeo/core/config.py` | Keep raw `PREDICTION_ATTRS`; add `prediction_attrs_${modelId}_v${version}`. |
| Sidecar utilities | `hastelib/src/hastegeo/core/utils/` | Own shared sidecar build/write helpers. |
| Prediction editing processor/API | `hastelib/src/hastegeo/core/processors/`, `api/hastefuncapi/function_app.py` | Save GeoPackage + sidecar together and append metadata only after both are ready. |
| Prediction tiles/backfill | `hastelib/src/hastegeo/core/processors/prediction_tiles.py`, `api/hastefuncqueues/function_app.py` | Backfill missing version sidecars idempotently (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:148-165`, `hastelib/src/hastegeo/core/processors/prediction_tiles.py:304-340`). |
| REST API | `api/hastefuncapi/function_app.py` | Add version-aware artifact downloads and visualizer sidecar selection; reports keep newest default. |
| React UI | `ui/src/Components/Visualizer/` | Selector, disabled missing-sidecar state, map-only warning, dual-pane switching, and downloads. |

### Azure Services Affected

| Service | Change |
|---|---|
| Cosmos DB | Existing Model documents gain optional `predictionAttrsUrl` inside edited-version entries. |
| Blob Storage | Stores one versioned sidecar per edited GeoPackage version. |
| Azure Functions | Save and artifact routes resolve versioned sidecars/downloads. |
| Azure Queue / Batch | Prediction-edit prep job backfills historical version sidecars. |

## Consequences

- **Easier:** The map renders raw and edited versions through one code path;
  downloads are authenticated through one route; raw output stays auditable.
- **Harder:** Save must coordinate two derived artifacts, historical versions
  need backfill, and the UI must explain the map/report split.
- **New constraints:** Do not advertise a version without both `gpkgUrl` and
  `predictionAttrsUrl`; do not generate sidecars in GET/read handlers; do not
  introduce an active-version pointer.
- **Accepted trade-off:** The map can show raw or v2 while reports use newest
  v3. This is intentional and must be explicit in the UI.
- **Backfill window:** Before backfill completes, pre-existing versions cannot
  be selected. The selector must disable them and say why.
- **Swipe-map constraint:** Both panes must switch together because feature-state
  is per renderer; a partial switch leaves stale colors on one side.
- **Known semantic gap:** Validation reads edited `damaged`, but Assessment
  counts still threshold preserved `damage_pct_0m`; version selection does not
  solve that.
- **Known concurrency gap:** No 409/ETag handling for concurrent saves is added
  by this ADR amendment.
- **Impact on Docker Compose local dev stack:** No new storage service; local
  Azurite stores additional versioned sidecar blobs.
- **Impact on CI/CD workflows:** No workflow change expected unless automated
  browser/Playwright tests are added later.
