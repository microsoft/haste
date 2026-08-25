# Technical Design: Prediction Editing

**Contents:** [Overview](#overview) · [Architecture](#architecture) · [API Design](#api-design) · [Behavior & Logic](#behavior--logic) · [Configuration](#configuration) · [Observability](#observability) · [Open Questions](#open-questions)

## Overview

Prediction editing is a mode of the existing **View Results** page. The page
already owns the two-map swipe view, imagery metadata, raster overlays, vector
footprints, edit panel, and save action; this design adds version selection and
per-version downloads without introducing a standalone editor route
(`ui/src/Components/AppBody.jsx:73-75`,
`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`).

The important data-model constraint is that the sidecar rendered by the browser
is currently keyed per model, not per version:
`PREDICTION_ATTRS = Template("prediction_attrs_${modelId}")`
(`hastelib/src/hastegeo/core/config.py:172`). That raw sidecar cannot render an
edited GeoPackage whose `damaged` values have changed. Each saved edited version
therefore gets its own sidecar, `prediction_attrs_${modelId}_v${version}`, and
`EditedPredictionVersion` records both the GeoPackage URL and sidecar URL.

Version selection is **map-only**. The selector refetches
`GetVisualizerResults?version=N`, swaps the map's sidecar/source state, and lets
analysts inspect or download that version. Assessment and Validation reports
continue to call their endpoints without the selector's version and therefore
continue to use the newest edited version by default. This accepted trade-off
keeps ADR-0005's no-active-pointer decision; the UI must make the possible
map/report mismatch explicit (`api/hastefuncapi/function_app.py:4607-4688`,
`api/hastefuncapi/function_app.py:4929-5027`).

## Architecture

### Component Diagram

```text
React View Results
  ├─ version selector + map-only warning
  ├─ per-version download button
  ├─ edit panel history row downloads
  └─ both swipe panes load one selected sidecar
          │
          ▼
hastefuncapi
  ├─ GetVisualizerResults?version=N
  ├─ GetModelArtifact?kind=prediction_attrs&version=N
  ├─ GetModelArtifact?kind=gpkg&version=N
  └─ PutEditedPredictions writes GPKG + sidecar together
          │
          ▼
hastegeo core
  ├─ prediction_edits applies overrides and stores edited GPKG
  ├─ core.utils.prediction_attrs builds/writes sidecars
  └─ prediction_tiles backfills missing version sidecars
          │
          ▼
Blob + Cosmos
  ├─ edited_predictions_{modelId}_v{version}.gpkg
  ├─ prediction_attrs_{modelId}_v{version}.json
  └─ Model.editedPredictions[] records both URLs
```

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Shared prediction-attribute helpers | `hastelib/src/hastegeo/core/utils/prediction_attrs.py` | Build and write raw or edited sidecar JSON from a GeoPackage plus source footprints; moved out of the workflow that previously defined `build_prediction_attrs`/`write_prediction_attrs` (`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`) | Python / Fiona |
| Versioned sidecar artifact | `hastelib/src/hastegeo/core/config.py` | Add `prediction_attrs_${modelId}_v${version}` alongside raw `prediction_attrs_${modelId}` (`hastelib/src/hastegeo/core/config.py:168-180`) | Python config |
| Versioned artifact resolver | `api/hastefuncapi/function_app.py` + `hastegeo.core.utils.predictions` | Resolve raw, newest, and explicit edited `gpkg`/`prediction_attrs` artifacts for `GetModelArtifact` and `GetVisualizerResults` | Python |
| Version selector | `ui/src/Components/Visualizer/` | Select raw or a saved version, refetch the map only, disable versions missing sidecars, and show report-mismatch copy | React / Fluent UI |
| Version download controls | `ui/src/Components/Visualizer/PredictionEditPanel.jsx` and View Results controls | Download the selected version or a row's version through `GetModelArtifact` | React |
| Backfill mode | `hastelib/src/hastegeo/core/processors/prediction_tiles.py` / queue worker | Build missing per-version sidecars once and skip already-ready versions (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:148-165`, `hastelib/src/hastegeo/core/processors/prediction_tiles.py:304-340`) | Python / queue worker |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| Model schema | `hastelib/src/hastegeo/core/models/projects.py` | Extend `EditedPredictionVersion` with `predictionAttrsUrl`; existing fields are at `hastelib/src/hastegeo/core/models/projects.py:343-389`. |
| Save route | `api/hastefuncapi/function_app.py` | `PutEditedPredictions` currently appends a version after writing the GeoPackage (`api/hastefuncapi/function_app.py:3302-3325`); it must adopt `save_edited_version`, which builds/stores the matching sidecar before appending (`hastelib/src/hastegeo/core/processors/prediction_edits.py:520-608`). |
| Visualizer payload model | `hastelib/src/hastegeo/core/models/visualizer.py` | Add an `isNewestPredictionVersion` boolean to the existing version fields (`hastelib/src/hastegeo/core/models/visualizer.py:65-78`). |
| Visualizer payload builder | `hastelib/src/hastegeo/core/processors/visualizer.py` | Build `predictionAttrsUrl` with the selected version query instead of always using the raw/model-scoped URL (`hastelib/src/hastegeo/core/processors/visualizer.py:272-329`). |
| Artifact route | `api/hastefuncapi/function_app.py` | Extend `GetModelArtifact` so `kind=gpkg` and `kind=prediction_attrs` accept `version`; current dispatch is field-based (`api/hastefuncapi/function_app.py:1400-1570`). |
| Visualizer fetch | `ui/src/Components/Visualizer/Visualizer.jsx` | Include selector state in `GetVisualizerResults`; current fetch omits `version` (`ui/src/Components/Visualizer/Visualizer.jsx:213-223`). |
| Model-row download | `ui/src/Components/ProjectManagement/ModelResultsButton.jsx` | Replace direct URL rewrite/download for prediction GPKGs with `GetModelArtifact` where this flow exposes prediction downloads (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:61-69`, `ui/src/Components/ProjectManagement/ModelResultsButton.jsx:113-119`). |

## API Design

The route names follow the current Azure Functions convention in
`function_app.py`. Endpoints use the existing function/SWA auth path and keep
non-HTTP logic in `hastegeo`.

### `GET /api/GetVisualizerResults` (modified)

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Return the View Results payload for one selected prediction
source. Omitting `version` selects the newest edited version when one exists;
`version=0` selects raw; `version=N` selects that edited version. Unknown
positive versions return 404, malformed values return 400
(`api/hastefuncapi/function_app.py:2307-2340`,
`api/hastefuncapi/function_app.py:2386-2397`).

**Additional/changed response fields:**

| Field | Type | Description |
|---|---|---|
| `predictionAttrsUrl` | string/null | API-relative `GetModelArtifact?kind=prediction_attrs&version=<selected>` for the selected raw or edited sidecar. |
| `predictionVersion` | int/null | Positive edited version on the map; `null` for raw. |
| `predictionVersions` | array | `Model.editedPredictions`, newest first, including `predictionAttrsUrl` readiness. |
| `isNewestPredictionVersion` | bool | `true` when the map selection is the newest edited version, or raw when no edits exist; `false` for raw/older selections when a newer edit exists. |

**Decision:** This endpoint controls the map only. The UI must not pass the
selector's version to Validation or Assessment report buttons.

### `GET /api/GetModelArtifact` (modified)

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Stream model artifacts through the Functions app so auth,
managed identity, content disposition, and HTTP Range stay centralized. The route
already serves `gpkg` and `prediction_attrs` from model fields
(`api/hastefuncapi/function_app.py:1400-1570`). It now resolves those two kinds
by optional `version`.

| Kind | Version handling | Returns |
|---|---|---|
| `gpkg` | omitted or `version=0` = raw `Model.gpkgUrl`; positive `version=N` = `EditedPredictionVersion.gpkgUrl`; unknown `N` = 404 | GeoPackage attachment |
| `prediction_attrs` | omitted or `version=0` = raw `Model.predictionAttrsUrl`; positive `version=N` = `EditedPredictionVersion.predictionAttrsUrl`; unknown/missing sidecar = 404 | JSON sidecar |
| `footprint_pmtiles` | ignores prediction version | Shared layer or embedding PMTiles |

New UI downloads should always pass an explicit version (`0` for raw or `N` for
an edited row) so the selected artifact is unambiguous.

### `PUT /api/PutEditedPredictions` (modified)

**Auth:** `func.AuthLevel.FUNCTION`

**Description:** Apply overrides and thresholds, write a new edited GeoPackage,
write the matching versioned sidecar, and append metadata. The core helper now stores the GPKG and sidecar together
(`hastelib/src/hastegeo/core/processors/prediction_edits.py:520-608`). The API
route must adopt it before appending metadata
(`api/hastefuncapi/function_app.py:3186-3325`).

**Response (200):**

```json
{
  "version": 2,
  "gpkgUrl": "https://storage/.../edited_predictions_5553_v2.gpkg",
  "predictionAttrsUrl": "https://storage/.../prediction_attrs_5553_v2.json",
  "editedCount": 17
}
```

**Failure rule:** If the sidecar cannot be generated or uploaded, the route must
not advertise the version in `Model.editedPredictions`. The sidecar is derived,
but it must agree with the GeoPackage or the map can silently draw wrong colors.

**Known limitation:** The route still has no 409/ETag concurrency protection for
simultaneous saves. That remains out of scope for this change.

### `GET /api/GetEditedPredictionVersions` (modified)

**Auth:** `func.AuthLevel.FUNCTION`

Returns the same version metadata list as before, now including
`predictionAttrsUrl` when present. Versions missing that URL are saved artifacts
but are not selectable until backfill completes.

### `PUT /api/PutPreparePredictionTilesQueueMessage` (modified)

**Auth:** `func.AuthLevel.FUNCTION`

Adds idempotent backfill support to the existing prediction-tiles job. The
request can include:

```json
{
  "projectId": "string",
  "imageLayerId": "string",
  "modelId": "string",
  "force": false,
  "backfillVersions": true
}
```

When `backfillVersions` is true, the worker builds missing
`prediction_attrs_${modelId}_v${version}` sidecars for existing
`Model.editedPredictions[]`. It skips versions with sidecars unless `force` is
true. It does not run from `GetVisualizerResults` or from `GetModelArtifact`, so
read requests stay free of generation logic.

### `GET /api/GetValidationReport`, `GET /api/GetAssessmentReport` (unchanged for selector)

Both endpoints keep their existing version contract: omitted = newest edited,
`version=0` = raw, explicit `version=N` = that edit, unknown `N` = 404
(`api/hastefuncapi/function_app.py:4607-4688`,
`api/hastefuncapi/function_app.py:4929-5027`). The View Results selector does not
modify these report requests.

The semantic gap remains: edited GeoPackages override `damaged` but preserve
`damage_pct_0m`. Validation reads `damaged`; Assessment thresholds
`damage_pct_0m`, so manual overrides still do not move Assessment counts
(`api/hastefuncapi/function_app.py:4808-4827`,
`api/hastefuncapi/function_app.py:5081-5092`).

### Internal Interfaces (hastegeo)

| Module | Function/Class | Signature / Contract | Description |
|---|---|---|---|
| `core/models/projects.py` | `EditedPredictionVersion` | add `predictionAttrsUrl: Optional[str]` | Version metadata carries both renderable artifacts. |
| `core/utils/prediction_attrs.py` | `build_prediction_attrs`, `write_prediction_attrs` | `(predictions_path, footprints_path, attrs_path?)` | Shared sidecar generation for raw, edited, and backfill paths. |
| `core/processors/prediction_edits.py` | `store_version_attrs`, `save_edited_version` | returns GPKG URL and sidecar URL | Writes derived artifacts for one version (`hastelib/src/hastegeo/core/processors/prediction_edits.py:437-488`, `hastelib/src/hastegeo/core/processors/prediction_edits.py:520-608`). |
| `core/processors/prediction_tiles.py` | `versions_needing_attrs`, `request_preparation` | `(model, image_layer, force=False, backfill_versions=True)` | Idempotently fills missing sidecars (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:148-165`, `hastelib/src/hastegeo/core/processors/prediction_tiles.py:304-340`). |
| `core/processors/visualizer.py` | `model_artifact_url` | add optional `version` query | Builds versioned API-relative artifact URLs. |

## Behavior & Logic

### Core Flow

1. Analyst opens **View Results** for a model.
2. `GetVisualizerResults` defaults to the newest edited version if one exists.
3. The payload lists raw plus edited versions, marks which one is newest, and
   includes the selected version's `predictionAttrsUrl`.
4. The UI downloads PMTiles and the selected sidecar through `GetModelArtifact`.
5. The analyst changes the selector. The UI refetches `GetVisualizerResults` for
   that version and switches both swipe panes together.
6. If the selected version is not newest, the UI states that Assessment and
   Validation reports still use the newest version.
7. The analyst downloads the selected map version beside the selector, or a
   specific saved row from the edit panel history.
8. When the analyst saves a new edit, the backend writes the edited GeoPackage
   and matching sidecar, records both URLs, and returns them.
9. Pre-existing saved versions lacking sidecars are disabled until the backfill
   job populates them.

### Version selection rule

| Selector value | Map source | Reports from View Results buttons |
|---|---|---|
| Latest / omitted | newest edited version, or raw if no edits | newest edited version, or raw if no edits |
| Raw (`version=0`) | raw `Model.gpkgUrl` + raw `Model.predictionAttrsUrl` | newest edited version if edits exist |
| Edited vN | `EditedPredictionVersion.gpkgUrl` + `predictionAttrsUrl` for vN | newest edited version if edits exist |

This split is a deliberate product decision. It avoids adding mutable global
state and keeps report defaults stable, at the cost of possible map/report
mismatch that the UI must disclose.

### Sidecar consistency rule

A version is selectable only when both artifacts exist:

```text
EditedPredictionVersion.gpkgUrl exists
AND EditedPredictionVersion.predictionAttrsUrl exists
```

The sidecar must be derived from the same edited GeoPackage rows. Building it
from raw predictions, lazily on first selection, or through a separate code path
that can drift is not allowed.

### Backfill rule

Backfill is a one-time, idempotent prediction-tiles job mode. It targets existing
versions that predate `predictionAttrsUrl`, including dev model `0448` v1 and
`5553` v1. During the backfill window, those versions remain visible in history
but disabled in the selector and in map-only download controls that require a
renderable sidecar.

### UI behavior

- The selector includes Raw plus saved edited versions.
- Versions missing sidecars are disabled and explain that the backfill job has
  not finished.
- The download beside the selector downloads the selected GeoPackage through
  `GetModelArtifact?kind=gpkg&version=<selected>`.
- Each version-history row has its own download action using the row's version.
- The map-only warning appears when selected version is not newest.
- Both panes must reset source URL, sidecar cache, feature-state colors, and
  selected/edited class baselines together. This class of partial-switch defect
  has occurred before because feature-state is per renderer
  (`ui/src/Components/Visualizer/usePredictionFootprints.js:19-25`,
  `ui/src/Components/Visualizer/usePredictionFootprints.js:212-228`).

### Edge Cases

| Case | Expected Behavior |
|---|---|
| Missing raw `Model.gpkgUrl` | View/edit/download unavailable; artifact request returns 404. |
| Unknown positive version | `GetVisualizerResults` and `GetModelArtifact` return 404. |
| Malformed version | Return 400. |
| Edited version lacks sidecar | Selector disables it and says backfill has not completed. |
| Backfill rerun | Skips versions with sidecars; fills only missing ones unless `force=true`. |
| Sidecar write fails during save | Do not append/select the version; return an error. |
| Concurrent saves | Known gap: no 409 conflict handling yet. |
| Map shows older/raw while reports use newest | UI shows explicit warning; this is accepted behavior. |
| Assessment counts ignore manual overrides | Still out of scope because `damage_pct_0m` is preserved. |
| No Playwright coverage | Documented validation gap; repo has no Playwright config (`ui/package.json:6-15`, `ui/package.json:62-75`). |

### Error Handling

| Error Condition | Response | Recovery |
|---|---|---|
| Versioned sidecar missing | 404 from artifact route; disabled UI state | Run or wait for backfill. |
| Backfill job fails | Version remains disabled with status details | Retry idempotent backfill. |
| Blob upload fails on sidecar save | Save returns 500 and does not advertise version | Retry save; inspect orphan cleanup if needed. |
| Metadata save fails after artifacts upload | Save returns 500; artifacts may be orphaned | Retry after checking version allocation. |
| Unknown explicit prediction version | 404 | Refresh version list or use raw/latest. |

### Known limitations / follow-ups

- No 409 on concurrent edited-version saves; add ETag, lease, or retry-safe
  allocation before multi-analyst editing.
- No Playwright/browser coverage exists today.
- Assessment report counts still threshold preserved `damage_pct_0m`; version
  selection does not address this.
- Publishing edited versions remains out of scope.
- Raw producers still lack explicit `overture_id` and can rely on positional
  joins.

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `prediction_edit_prep_queue_name` | string | `prediction-edit-prep-queue` | `local.settings.json` / App Settings / `Config.get_queue_config()` | Queue used for PMTiles, raw sidecar prep, and edited-version sidecar backfill. |

No new feature flag is part of this design. If production needs a kill switch,
add API/UI flags before broad rollout.

## Observability

- **Logs:** Record selected version, newest flag, sidecar URL presence, disabled
  sidecar state, save version allocation, and backfill skip/build counts. Do not
  log SAS tokens.
- **Metrics:** Track sidecar save failures, backfill duration, disabled-version
  counts, versioned downloads, and report/map mismatch warnings shown.
- **Queue depth:** Monitor prediction-edit prep queue during backfill.
- **UI errors:** Surface missing sidecars, map switch failures, and download
  failures with retry guidance.

## Open Questions

- [ ] Should edit application move to an async queue if production layers exceed
      Azure Functions request-timeout or memory budgets?
- [ ] Should edited-version saves use Cosmos ETags, blob leases, or another
      optimistic-concurrency mechanism to prevent concurrent version collisions?
- [ ] Should Assessment reports use edited `damaged`, persist edited
      `damage_pct_0m`, expose override-aware counts separately, or keep the
      current threshold-only interpretation?
- [ ] Should raw prediction producers add explicit `overture_id` and stop
      relying on positional joins before this feature is broadly rolled out?
