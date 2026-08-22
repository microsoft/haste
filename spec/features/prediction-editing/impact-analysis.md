# Impact Analysis: Prediction Editing

**Contents:** [Scope of Change](#scope-of-change) · [Azure Service Impact](#azure-service-impact) · [Dependency Analysis](#dependency-analysis) · [Risk Assessment](#risk-assessment) · [Performance Impact](#performance-impact) · [Security Impact](#security-impact) · [Compliance & Data Impact](#compliance--data-impact) · [Rollback Assessment](#rollback-assessment)

## Scope of Change

### HASTE Components Affected

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core library | `hastelib/src/hastegeo/core/models/`, `hastelib/src/hastegeo/core/processors/`, `hastelib/src/hastegeo/core/utils/`, `hastelib/src/hastegeo/core/config.py` | modified / new; adds version metadata, vector-results payload assembly, readiness, prep, source resolution, and edit writer | high |
| REST API | `api/hastefuncapi/function_app.py` | new edit/prep/version endpoints; vector-first `GetVisualizerResults`; `version` support in visualizer/validation/assessment readers; modified artifact dispatch | high |
| Queue workers | `api/hastefuncqueues/function_app.py` | new prep trigger with model-scoped and layer-only modes | medium |
| React UI | `ui/src/Components/ProjectManagement/`, `ui/src/Components/Visualizer/` | Results menu gating, embedding View Results entry, vector-first viewer, edit mode, and removal of standalone Edit route/screen | high |
| Docker config | `docker/training/` | no new package expected; uses existing `tippecanoe` in training env | low |
| CI/CD / infra | `.github/workflows/...`, `infra/modules/functions.bicep` | no workflow change; explicit Bicep app-setting parity for the prep queue was skipped to avoid `infra/main.json` drift | low |

## Azure Service Impact

| Service | Change | New Cost Impact |
|---|---|---|
| Cosmos DB | Model and ImageLayer documents gain optional fields; Model appends small version records; model reads derive `predictionsReady` in memory | low RU increase per session/save |
| Blob Storage | Stores PMTiles, sidecars, and one edited GeoPackage per save | proportional to footprint count and version count |
| Queue Storage | Adds prep messages for missing PMTiles/sidecars and layer-only footprint tiling | low; bursty when results are first opened for older layers |
| Azure Functions | Adds edit/prep/version routes and expands visualizer/report readers | low to medium CPU/memory during GeoPackage reads and saves |
| Azure Batch | Reuses existing runner/training image path for `tippecanoe` prep | low; CPU-bound tile jobs may occupy existing nodes |
| Static Web Apps | View Results now downloads and renders vector footprint artifacts; edit mode runs in the existing route | low hosting impact; browser memory is the main concern |

## Dependency Analysis

### Upstream Dependencies (things this feature needs)

| Dependency | Type | Status | Risk if Unavailable |
|---|---|---|---|
| Raw prediction GeoPackage (`Model.gpkgUrl`) | artifact | available after trained inference or embedding predictions | Edit session cannot open; save cannot derive a version. |
| Vector readiness flag (`predictionsReady`) | API-derived field | returned by model payload endpoints | UI falls back to legacy checks, but stale clients can diverge until refreshed. |
| Source building footprints (`ImageLayer.buildingFootprintsUrl`) | artifact | available after imagery prep | Cannot derive `overture_id`, build layer PMTiles, or validate row-order mapping. |
| Layer/model PMTiles (`footprintPmtilesUrl` or embedding `pmtilesUrl`) | artifact | generated at layer creation or on demand | Results page shows a preparing state and queues prep; without it no vector layer draws. |
| Prediction attribute sidecar (`Model.predictionAttrsUrl`) | artifact | generated on demand per model | Results page can show imagery but not predicted footprints or edit mode. |
| `tippecanoe` in training image | container tool | available only in training env | PMTiles cannot be generated from Functions inline (`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:40-45`). |
| PMTiles JS support | UI dependency | already present | Visualizer cannot stream full geometry efficiently. |
| Azure Maps | UI mapping | available in app | Results viewer loses primary visual interaction surface. |

### Downstream Impact (things affected by this feature)

| Consumer | How Affected | Breaking? | Migration Needed? |
|---|---|---|---|
| `hastefuncapi` callers | New endpoints and artifact kinds; `GetVisualizerResults` adds vector fields and nullable raster fields | low risk | callers must null-check `predictedDamageLayer` and `predictionsLayer` (`docs/api/hastefuncapi.md:124-131`) |
| React model rows | Results View gating now uses `predictionsReady`; embedding rows gain View Results; standalone Edit buttons are gone | no | no data migration |
| Existing Cosmos documents | Optional fields absent until touched/backfilled; derived `predictionsReady` not persisted | no | no blocking migration |
| Visualizer | Changed from raster-first to vector-first; embedding workflow now has a usable entry point | yes for code path | existing route remains `/visualizer/...` (`ui/src/Components/AppBody.jsx:73-75`) |
| Validation report | Defaults to newest edited version and supports `version`; reads edited `damaged` | behavioral change | document raw access with `version=0` (`docs/api/hastefuncapi.md:480-502`) |
| Assessment report | Defaults to newest edited version and supports `version`; still thresholds preserved `damage_pct_0m` | behavioral nuance | product follow-up required for override-aware counts |
| Data publishing | Uses unified completion/readiness rule for eligibility but does not publish edited versions | no | follow-up spec required |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| Positional row-order invariant breaks Overture id mapping | medium | high | Assert row count and row order in prep/save tests; never sort or spatial-join edited output; write explicit `overture_id` for audit. | `gis` |
| Classic inference can silently drop footprint rows before prediction output | medium | high | Capture as a follow-up: the current writer skips out-of-bounds geometries and writes only `valid_building_geoms`, which can invalidate the positional join (`docker/training/code/merge_with_building_footprints.py:151-190`, `docker/training/code/merge_with_building_footprints.py:239-258`). | `gis` |
| Raw prediction GeoPackages lack `overture_id` | high | medium | Edited outputs add `overture_id`; open a producer-side follow-up so raw outputs do not rely solely on row order (`api/hastefuncapi/function_app.py:2738-2815`). | `gis`, `backend-dev` |
| Editor default threshold and `GetAssessmentReport` default differ | medium | medium | Document the current split: editor defaults to `0.0` to reproduce raw stored predictions, while `GetAssessmentReport` still defaults to threshold `0.1`; add product follow-up if this confuses users. | `backend-dev` |
| Edited `damaged` moves validation metrics but assessment thresholds preserved `damage_pct_0m` | high | medium | Document the asymmetry and decide whether assessment should consume overrides differently (`api/hastefuncapi/function_app.py:4808-4827`, `hastelib/src/hastegeo/core/utils/assessment.py:187-190`). | `backend-dev`, `gis` |
| Large layers exceed memory in tile prep, artifact loading, or edit application | medium | high | Keep browser geometry in PMTiles; measure whole-GPKG reads; add performance tests; move save to async if needed. | `backend-dev`, `gis`, `ui` |
| HTTP handler tries to run `tippecanoe` inline | low | high | Keep PMTiles generation in `prediction-edit-prep-queue`; test absence of inline generation path. | `backend-dev` |
| Embedding `gpkgUrl` is treated as a full prediction set after Clear labels | medium | medium | Gate on server-derived `predictionsReady`; `predictedBuildingCount == 0` returns `no_buildings` (`hastelib/src/hastegeo/core/utils/model_readiness.py:168-198`). | `backend-dev`, `ui` |
| Edited artifact overwrites raw output | low | high | Never write to `Model.gpkgUrl`; use `EDITED_PREDICTIONS_GPKG` with version in the name and append metadata. | `backend-dev` |
| UI version history appears selectable but does not switch versions | medium | low | Label active version clearly; document read-only history and add version-switching follow-up (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`). | `ui` |
| UI hard-coded colors fail dark mode | medium | medium | Require `makeStyles` + Fluent tokens; add UI review checklist item. | `ui` |
| UI lint remains red because of existing ESLint 9 flat-config mismatch | high | medium | Treat CI gate as no regression from baseline; record baseline failure and require targeted UI helper tests. | `ui-validation` |
| Concurrent edited-version saves collide | medium | medium | Current implementation has no 409/ETag conflict handling; add optimistic concurrency before relying on simultaneous multi-analyst saves. | `backend-dev` |
| Lack of browser/Playwright coverage misses visualizer regressions | high | medium | Add Playwright or explicitly waive with manual evidence; current repo has no Playwright config or dependency (`ui/package.json:6-15`, `ui/package.json:62-75`). | `ui-validation` |

## Performance Impact

- **Visualizer latency:** `GetVisualizerResults` may read the selected GeoPackage
  to populate `flavor`, `supportsThreshold`, and `buildingCount`. If that read
  fails, imagery/readiness still return (`api/hastefuncapi/function_app.py:2397-2423`).
- **API latency:** `GetPredictionEditSession` is read-only and does not enqueue,
  but it downloads the raw prediction GeoPackage to detect flavor and count rows.
  `PutPreparePredictionTilesQueueMessage` performs the queue request.
  `PutEditedPredictions` reads and writes a full GeoPackage in v1, so large
  layers may approach function timeout or memory limits.
- **Queue throughput:** New prep jobs are CPU and I/O bound. They should be
  idempotent and skip PMTiles or sidecar generation when artifacts already exist.
- **Tile serving:** The visualizer uses static PMTiles artifacts, not TiTiler for
  vector tiles. Tile serving load shifts to Function App streaming and
  Blob/download bandwidth.
- **Browser memory:** The UI downloads the PMTiles archive and sidecar once per
  visualizer route (`ui/src/Components/Visualizer/usePredictionArtifacts.js:177-221`).
- **Batch compute:** No GPU is needed. Existing training-image jobs may consume
  CPU on the current runner pool while generating PMTiles.
- **Storage I/O:** Each first results open may download PMTiles and sidecar data;
  each save writes a full edited GeoPackage.

## Security Impact

- [x] New API endpoints exposed? Use existing `func.AuthLevel.FUNCTION` and SWA
      auth pattern.
- [x] New data classification handled? Edited predictions are derived disaster
      assessment geospatial data, same sensitivity as raw model outputs.
- [x] Artifact access constrained? PMTiles and sidecars are streamed through
      `GetModelArtifact`, preserving server-side auth and managed identity
      rather than exposing raw blob URLs (`api/hastefuncapi/function_app.py:1435-1458`).
- [ ] MSAL/Entra ID auth changes? None expected.
- [ ] New secrets or connection strings required? None expected.
- [ ] CORS configuration changes in SWA? None expected.
- [ ] New federated credentials needed? None expected.

## Compliance & Data Impact

- [x] Geospatial data sovereignty concerns? Same as raw project artifacts;
      edited versions must stay in the project storage boundary.
- [x] Partner data sharing agreements affected? No external sharing automation
      in v1; downloads are existing-authenticated artifact access.
- [x] New data retention requirements? Versioned edited GeoPackages increase
      retained derived artifacts; retention follows project artifact retention.
- [x] Audit logging for new operations? Save logs should include project,
      model, version, editor identity when available, and edited count.
- [ ] Component Governance scan implications? None unless implementation adds
      dependencies; current design reuses existing packages.

## Rollback Assessment

- **Reversibility:** runtime behavior is reversible by redeploying the previous
  UI/API. The current implementation has no feature flag kill switch.
- **Cosmos data:** Old code ignores optional `editedPredictions`,
  `predictedBuildingCount`, `predictedAt`, `predictionAttrsUrl`,
  `predictionTilesJob`, `predictionTilesStatus`,
  `predictionTilesStatusMessage`, and `footprintPmtilesUrl`. Cleanup is
  optional, not required for rollback.
- **Blob data:** Edited GeoPackages, sidecars, and PMTiles are additive derived
  artifacts. They can be deleted by approved maintenance tooling if needed.
- **API:** New endpoints and artifact kinds are additive. `GetVisualizerResults`
  now returns nullable raster layers; reverting API restores the old raster-only
  contract if an external caller cannot tolerate nulls.
- **Reports:** If newest-edited defaults cause issues, callers can use
  `version=0` as an immediate raw-output workaround while API rollback is
  evaluated.
- **Estimated rollback time:** Immediate previous-build redeploy; less than 30
  minutes to redeploy a reverted UI/API if required.
