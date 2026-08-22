# Feature: Prediction Editing

**Status:** draft
**Author:** HASTE engineering team
**Date:** 2026-08-21
**Target Release:** TBD
**Priority:** P1
**Work Item:** —

**Contents:** [Summary](#summary) · [Motivation](#motivation) · [Success Criteria](#success-criteria) · [HASTE Components Affected](#haste-components-affected) · [Related Specs](#related-specs) · [Document Index](#document-index) · [Decision Log](#decision-log)

## Summary

Prediction editing is now a **mode inside the existing View Results page**, not
a standalone screen. Analysts open `/visualizer/:projectId/:imageLayerId/:modelId`
from the Results menu, then enter edit mode with the pencil next to Back or the
`E` shortcut; Done or `E` exits, with a discard-confirmation dialog for unsaved
edits (`ui/src/Components/AppBody.jsx:73-75`,
`ui/src/Components/Visualizer/Labels.jsx:8-12`,
`ui/src/Components/Visualizer/Labels.jsx:117-128`,
`ui/src/Components/Visualizer/Visualizer.jsx:457-605`).

The View Results page is vector-first for both prediction workflows. It draws
predicted building footprints from footprint PMTiles plus the prediction
attribute sidecar, artifacts both trained inference and embedding models can
provide; trained-inference rasters remain optional overlays and are nullable in
the payload (`hastelib/src/hastegeo/core/processors/visualizer.py:4-29`,
`hastelib/src/hastegeo/core/processors/visualizer.py:278-331`,
`hastelib/src/hastegeo/core/models/visualizer.py:45-82`). The embedding model
row now exposes View Results as the first Results menu action, so the embedding
workflow has a working results-viewer entry point
(`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:116-130`).

Each save still creates a new, numbered edited prediction GeoPackage (`edit_v1`,
`edit_v2`, …) as a derived artifact. The raw model output remains in
`Model.gpkgUrl`, while `GetVisualizerResults`, `GetValidationReport`, and
`GetAssessmentReport` default to the newest saved edit and accept an optional
`version` query parameter; `version=0` forces the raw output
(`hastelib/src/hastegeo/core/utils/predictions.py:332-401`,
`api/hastefuncapi/function_app.py:2386-2435`,
`api/hastefuncapi/function_app.py:4677-4688`,
`api/hastefuncapi/function_app.py:5017-5027`).

## Motivation

- Disaster analysts need a fast way to correct false positives, false negatives,
  and ambiguous buildings before handing outputs to response partners.
- The previous raster-only viewer could draw only the `_visualizer.tif` and
  `_predictions.tif` COGs produced by trained inference. Embedding predictions
  produce no raster, so vector PMTiles plus the attribute sidecar are now the
  shared results path (`hastelib/src/hastegeo/core/processors/visualizer.py:4-29`,
  `ui/src/Components/Visualizer/Visualizer.jsx:13-28`).
- Three call sites previously answered "does this model have results" from
  different fields. `hastegeo.core.utils.model_readiness` is now the single
  server-side rule, exposed as `predictionsReady` on model payloads and reused
  by publishing (`hastelib/src/hastegeo/core/utils/model_readiness.py:4-25`,
  `api/hastefuncapi/function_app.py:785-788`,
  `api/hastefuncapi/function_app.py:1262-1266`,
  `api/hastefuncapi/function_app.py:1380-1383`,
  `hastelib/src/hastegeo/core/publishing/source.py:116-124`).
- `GetBuildingFootprintsGeoJSON` remains a sampled preview path, not an editing
  data path. Editing requires the complete footprint PMTiles and sidecar route
  (`api/hastefuncapi/function_app.py:1400-1424`,
  `api/hastefuncapi/function_app.py:1453-1458`).
- HASTE still has no generic artifact versioning: edited outputs must be
  numbered derived artifacts rather than overwriting raw model outputs
  (`hastelib/src/hastegeo/core/models/projects.py:343-385`,
  `hastelib/src/hastegeo/core/processors/prediction_edits.py:1-19`,
  `hastelib/src/hastegeo/core/processors/prediction_edits.py:329-422`).

## Success Criteria

- [ ] Trained and embedding model rows expose **View** as the Results menu entry
      point, enabled from server-derived `predictionsReady` with legacy
      fallbacks; there are no model-row Edit buttons or `/edit-predictions/...`
      route (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:87-110`,
      `ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:85-130`,
      `ui/src/Components/AppBody.jsx:73-75`).
- [ ] `GetVisualizerResults` returns the vector artifacts and readiness for both
      workflows, while `predictedDamageLayer` and `predictionsLayer` are nullable
      trained-inference-only overlays; the full response shape remains aligned
      with `docs/api/hastefuncapi.md` (`docs/api/hastefuncapi.md:78-157`).
- [ ] Opening View Results for an embedding model renders a usable 200 payload
      and predicted footprints rather than an empty raster-only page
      (`hastelib/tests/core/processors/test_visualizer_payload.py:222-268`).
- [ ] The results page loads all predicted footprints through PMTiles and the
      prediction attribute sidecar; missing PMTiles or attributes are requested
      through the explicit prep PUT route and generated by a queued job, not by
      the GET handler (`ui/src/Components/Visualizer/usePredictionArtifacts.js:4-24`,
      `ui/src/Components/Visualizer/usePredictionArtifacts.js:224-299`,
      `hastelib/src/hastegeo/core/processors/prediction_tiles.py:251-370`).
- [ ] Analysts can enter edit mode with the pencil or `E`, click individual
      buildings, ctrl+drag box-select groups, set `Damaged`, `NotDamaged`, or
      `Unknown`, and leave through Done/`E` with unsaved-edits confirmation
      (`ui/src/Components/Visualizer/Visualizer.jsx:496-605`,
      `ui/src/Components/Visualizer/usePredictionFootprints.js:313-376`,
      `ui/src/Components/keyboardShortcuts.js:60-80`).
- [ ] Trained-inference models show live damage/unknown threshold sliders using
      `damage_pct_0m`; embedding models hide the sliders because their
      `damage_pct_0m` values are a degenerate 0.0/1.0 copy of `damaged`
      (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:346-397`,
      `api/hastefuncapi/function_app.py:2738-2815`).
- [ ] Saving creates `edit_v1`, `edit_v2`, … without mutating `Model.gpkgUrl` or
      the raw model output; the written edited GeoPackage preserves row order
      and adds `edited_class`, `edit_threshold`, and `overture_id`
      (`api/hastefuncapi/function_app.py:3181-3345`,
      `hastelib/src/hastegeo/core/processors/prediction_edits.py:226-308`).
- [ ] Saved versions are visible in the edit panel and the payload reports which
      version is on the map. Version switching in the UI is **not** wired yet:
      the history rows are read-only and the visualizer fetch does not append a
      `version` parameter (`ui/src/Components/Visualizer/Visualizer.jsx:213-223`,
      `ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`).
- [ ] Validation and assessment/report readers can see edited versions through
      `resolve_prediction_source`; `version=0` forces raw. The known asymmetry is
      documented: validation reads edited `damaged`, while assessment thresholds
      the preserved `damage_pct_0m` and therefore ignores per-building overrides
      for its threshold-based counts (`api/hastefuncapi/function_app.py:4808-4827`,
      `hastelib/src/hastegeo/core/utils/assessment.py:150-190`,
      `docs/api/hastefuncapi.md:480-502`).

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/models/` | add `EditedPredictionVersion`; add `Model.editedPredictions`, `Model.predictedBuildingCount`, `Model.predictedAt`, `Model.predictionAttrsUrl`, `Model.predictionTilesJob`, `Model.predictionTilesStatus`, `Model.predictionTilesStatusMessage`, and `ImageLayer.footprintPmtilesUrl`; add visualizer payload fields for vector artifacts, readiness, flavor, building count, and versions (`hastelib/src/hastegeo/core/models/projects.py:343-505`, `hastelib/src/hastegeo/core/models/projects.py:520-529`, `hastelib/src/hastegeo/core/models/projects.py:842-851`, `hastelib/src/hastegeo/core/models/visualizer.py:45-82`) |
| `hastelib/src/hastegeo/core/config.py` | add artifact templates for edited prediction GeoPackages, prediction attributes, and layer footprint PMTiles; add the prediction-edit prep queue config (`hastelib/src/hastegeo/core/config.py:112-118`, `hastelib/src/hastegeo/core/config.py:165-172`, `hastelib/src/hastegeo/core/config.py:341-347`) |
| `hastelib/src/hastegeo/core/processors/` | `prediction_edits.py` applies edits and stores versions; `prediction_tiles.py` queues/finalizes prep; `visualizer.py` assembles the vector-first results payload (`hastelib/src/hastegeo/core/processors/prediction_edits.py:1-19`, `hastelib/src/hastegeo/core/processors/prediction_tiles.py:4-84`, `hastelib/src/hastegeo/core/processors/visualizer.py:215-336`) |
| `hastelib/src/hastegeo/core/utils/` | `predictions.py` normalizes both prediction GeoPackage flavors and resolves raw vs edited versions; `model_readiness.py` owns the single results-readiness rule (`hastelib/src/hastegeo/core/utils/predictions.py:4-34`, `hastelib/src/hastegeo/core/utils/predictions.py:318-401`, `hastelib/src/hastegeo/core/utils/model_readiness.py:132-237`) |
| `hastelib/src/hastegeo/workflows/` | queued tile/sidecar preparation workflow that runs where `tippecanoe` is available (`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:4-46`, `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:322-416`) |
| `api/hastefuncapi/` | prediction edit session/prep/save/version endpoints; vector-first `GetVisualizerResults`; `version` support in visualizer, validation, and assessment reports; `GetModelArtifact` serves `footprint_pmtiles` and `prediction_attrs` (`api/hastefuncapi/function_app.py:1400-1510`, `api/hastefuncapi/function_app.py:2296-2435`, `api/hastefuncapi/function_app.py:2920-3420`, `api/hastefuncapi/function_app.py:4607-4688`, `api/hastefuncapi/function_app.py:4929-5027`) |
| `api/hastefuncqueues/` | prediction-edit prep queue trigger supports model-scoped and layer-only preparation (`api/hastefuncqueues/function_app.py:861-914`) |
| `ui/src/Components/ProjectManagement/` | Results menu View action gates on `predictionsReady`; embedding row gets View Results; standalone Edit buttons are removed (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:87-110`, `ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:85-130`) |
| `ui/src/Components/Visualizer/` | existing View Results page owns vector-footprint loading, status notes, edit mode, edit panel, save flow, version display, and keyboard shortcuts (`ui/src/Components/Visualizer/Visualizer.jsx:166-199`, `ui/src/Components/Visualizer/Visualizer.jsx:873-921`, `ui/src/Components/Visualizer/usePredictionArtifacts.js:177-221`, `ui/src/Components/Visualizer/usePredictionFootprints.js:838-902`) |
| `ui/src/util/pmtiles.js` | shared PMTiles protocol and in-memory source used by the visualizer's vector artifacts (`ui/src/Components/Visualizer/usePredictionArtifacts.js:25-32`, `ui/src/Components/Visualizer/usePredictionArtifacts.js:201-212`) |
| `.github/workflows/` | no expected dependency change; CI should enforce tests and no-regression UI lint baseline |

## Related Specs

| Spec | Relationship |
|---|---|
| [data-publishing](../data-publishing/) | related — edited versions are saved artifacts but are not publishable datasets in this feature |
| [open-data-catalog](../open-data-catalog/) | related — shares Azure Maps/TiTiler geospatial UI patterns and the queue-first approach for heavy geospatial work |
| [ADR-0005: Introduce Versioned Derived Prediction Artifacts](../../architecture/decisions/0005-versioned-derived-prediction-artifacts.md) | records the artifact-versioning decision for edited prediction GeoPackages and the no-mutable-pointer reader rule |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [plan.md](plan.md) | Execution plan, milestones, phases | draft |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius | draft |
| [user-stories.md](user-stories.md) | User stories & acceptance criteria | draft |
| [design.md](design.md) | Technical design & API contracts | draft |
| [data-model.md](data-model.md) | Cosmos DB / Blob / Data Lake schema changes | draft |
| [test-plan.md](test-plan.md) | Test strategy & coverage matrix | draft |
| [rollout.md](rollout.md) | Rollout strategy, flags, rollback | draft |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-08-21 | Support both trained-inference and embedding workflows | Analysts need one review/edit entry point regardless of how predictions were produced. |
| 2026-08-21 | Store saves as numbered derived artifacts (`edit_v1`, `edit_v2`, …) | HASTE has no generic artifact versioning today, and overwriting `Model.gpkgUrl` would clobber the raw model output. |
| 2026-08-21 | Use PMTiles plus a columnar JSON attribute sidecar for the full browser dataset | Existing full-attribute APIs do not exist, and the sampled GeoJSON route is capped at 2,000 features. |
| 2026-08-21 | Keep `GetPredictionEditSession` read-only and queue prep through `PutPreparePredictionTilesQueueMessage` | `tippecanoe` is installed in the training image only, so HTTP handlers must not generate tiles inline (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:13-19`, `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:40-45`). |
| 2026-08-22 | Fold prediction editing into the existing View Results page | The implementation removed the standalone `/edit-predictions/...` route and uses the visualizer pencil/`E` affordance instead (`ui/src/Components/AppBody.jsx:73-75`, `ui/src/Components/Visualizer/Labels.jsx:117-128`). |
| 2026-08-22 | Make the results viewer vector-first and treat rasters as optional trained-inference overlays | Embedding models produce no rasters but can provide the same footprint PMTiles and sidecar as trained models (`hastelib/src/hastegeo/core/processors/visualizer.py:4-29`, `hastelib/src/hastegeo/core/models/visualizer.py:55-82`). |
| 2026-08-22 | Centralize model results readiness server-side | `predictionsReady` now comes from `model_readiness.py` and is stamped onto model payloads instead of being derived differently in each UI/publishing call site (`hastelib/src/hastegeo/core/utils/model_readiness.py:132-237`). |
| 2026-08-22 | Let readers default to the newest edited prediction version, with explicit `version` override and `version=0` raw | The no-mutable-pointer ADR still holds, while edited versions now reach visualizer, validation, and assessment readers (`hastelib/src/hastegeo/core/utils/predictions.py:332-401`, `docs/api/hastefuncapi.md:480-502`). |
