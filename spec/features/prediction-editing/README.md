# Feature: Prediction Editing

**Status:** draft
**Author:** HASTE engineering team
**Date:** 2026-08-21
**Target Release:** TBD
**Priority:** P1
**Work Item:** —

**Contents:** [Summary](#summary) · [Motivation](#motivation) · [Success Criteria](#success-criteria) · [HASTE Components Affected](#haste-components-affected) · [Related Specs](#related-specs) · [Document Index](#document-index) · [Decision Log](#decision-log)

## Summary

Prediction editing remains a **mode inside the existing View Results page**, not
a standalone screen. Analysts open `/visualizer/:projectId/:imageLayerId/:modelId`,
enter edit mode with the pencil next to Back or the `E` shortcut, and save
append-only edited prediction GeoPackages as `edit_v1`, `edit_v2`, and later
versions without mutating raw `Model.gpkgUrl` (`ui/src/Components/AppBody.jsx:73-75`,
`ui/src/Components/Visualizer/Labels.jsx:117-128`,
`api/hastefuncapi/function_app.py:3186-3325`).

This extension adds version selection and per-version downloads to View Results.
The selector changes **only the map**: Assessment and Validation reports continue
to read the newest edited version, even when the map is showing raw or an older
version. That trade-off is intentional to avoid adding an active-version pointer;
the UI must state the mismatch whenever the selected map version is not newest
(`api/hastefuncapi/function_app.py:4607-4688`,
`api/hastefuncapi/function_app.py:4929-5027`).

The architectural fix is versioned prediction-attribute sidecars. The current
sidecar is model-scoped (`prediction_attrs_${modelId}`) and describes only raw
predictions (`hastelib/src/hastegeo/core/config.py:172`,
`hastelib/src/hastegeo/core/models/projects.py:529-535`). Each saved edited
GeoPackage must now get a matching derived sidecar named
`prediction_attrs_${modelId}_v${version}` and recorded on its
`EditedPredictionVersion`. Rendering a saved version then uses the same vector
code path as raw rendering, with different `GetModelArtifact` URLs.

## Motivation

- Analysts need to compare raw and edited outputs on the map, then download the
  exact GeoPackage version they intend to share.
- The vector viewer colors PMTiles from a compact JSON sidecar, not from the
  GeoPackage directly. Without a per-version sidecar, selecting an edited GPKG
  would silently render raw classes (`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`).
- Downloads should use `GetModelArtifact` so authentication, managed identity,
  and HTTP Range behavior stay centralized instead of relying on direct SAS URL
  rewriting (`api/hastefuncapi/function_app.py:1430-1570`,
  `ui/src/Components/ProjectManagement/ModelResultsButton.jsx:61-69`).
- Pre-existing edited versions need a one-time backfill. The read path must stay
  free of sidecar generation logic, so the selector disables versions whose
  sidecar has not been generated yet.

## Success Criteria

- [ ] Saving an edited version writes both
      `edited_predictions_${modelId}_v${version}.gpkg` and
      `prediction_attrs_${modelId}_v${version}` in the same call path, then
      appends one `EditedPredictionVersion` with both URLs.
- [ ] `build_prediction_attrs` and `write_prediction_attrs` live in
      `hastegeo.core.utils` so the Functions app can build sidecars without
      importing the training-image workflow that previously held them
      (`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`).
- [ ] `GetModelArtifact` accepts optional `version` for `kind=gpkg` and
      `kind=prediction_attrs`; `version=0` returns raw output, positive versions
      return edited artifacts, and unknown versions return 404
      (`api/hastefuncapi/function_app.py:1400-1570`).
- [ ] `GetVisualizerResults?version=N` returns the selected version's
      `predictionAttrsUrl`, `predictionVersion`, and `isNewestPredictionVersion`
      flag. Omitting `version` keeps the default newest-edited map behavior.
- [ ] The View Results version selector refetches the map only. It does not
      change Assessment or Validation report inputs; the UI states when the map
      and reports can disagree.
- [ ] Both swipe panes switch together when the selected version changes. Feature
      state is per renderer, so source, sidecar, class cache, and repaint state
      must update for both panes in one transition
      (`ui/src/Components/Visualizer/usePredictionFootprints.js:19-25`,
      `ui/src/Components/Visualizer/usePredictionFootprints.js:212-228`).
- [ ] Download buttons appear beside the View Results selector and on each edit
      panel history row. They use `GetModelArtifact?kind=gpkg&version=N` instead
      of direct blob/SAS URL rewriting.
- [ ] The prediction-tiles job has an idempotent backfill mode that builds
      missing per-version sidecars and skips versions already carrying a sidecar.
      Dev models `0448` v1 and `5553` v1 are the known initial backfill targets.
- [ ] During the backfill window, versions without sidecars are visible but
      disabled in the selector with an explanation rather than rendering an
      empty or raw-colored map.
- [ ] Known out-of-scope gaps remain documented: no concurrent-save 409, no
      Playwright coverage, and Assessment counts still threshold preserved
      `damage_pct_0m` even though Validation reads edited `damaged`.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/models/` | Extend `EditedPredictionVersion` with a per-version sidecar URL while keeping `Model.gpkgUrl` raw and `Model.predictionAttrsUrl` raw/model-scoped (`hastelib/src/hastegeo/core/models/projects.py:343-389`, `hastelib/src/hastegeo/core/models/projects.py:529-535`). |
| `hastelib/src/hastegeo/core/config.py` | Keep raw `PREDICTION_ATTRS = Template("prediction_attrs_${modelId}")` and add a versioned sidecar artifact template `prediction_attrs_${modelId}_v${version}` (`hastelib/src/hastegeo/core/config.py:168-180`). |
| `hastelib/src/hastegeo/core/utils/` | Own shared prediction-attribute sidecar building/writing so API save and queue backfill use the same logic. |
| `hastelib/src/hastegeo/core/processors/` | Save edited GeoPackage and sidecar together; prediction-tiles processor adds idempotent backfill mode. |
| `hastelib/src/hastegeo/workflows/` | Continue queued PMTiles/raw-sidecar preparation, but import shared sidecar helpers instead of defining them in the workflow (`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:77-92`, `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:601-610`). |
| `api/hastefuncapi/` | Extend `GetModelArtifact`, `GetVisualizerResults`, and `PutEditedPredictions` for versioned sidecars and downloads; reports keep newest-version defaults (`api/hastefuncapi/function_app.py:1430-1570`, `api/hastefuncapi/function_app.py:2307-2435`, `api/hastefuncapi/function_app.py:3186-3325`). |
| `api/hastefuncqueues/` | Run backfill through the existing prediction-edit prep queue rather than generating sidecars lazily on GET. |
| `ui/src/Components/Visualizer/` | Add the selector, map-only warning, disabled missing-sidecar states, dual-pane switching, and per-row downloads. |
| `ui/src/Components/ProjectManagement/` | Replace direct GeoPackage blob download paths with `GetModelArtifact` where prediction downloads are exposed (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:113-119`). |
| `.github/workflows/` | No new workflow is expected; validation remains targeted backend tests plus UI helper tests and documented Playwright gap. |

## Related Specs

| Spec | Relationship |
|---|---|
| [data-publishing](../data-publishing/) | related — edited versions are saved artifacts but are not publishable datasets in this feature |
| [open-data-catalog](../open-data-catalog/) | related — shares Azure Maps/TiTiler geospatial UI patterns and the queue-first approach for heavy geospatial work |
| [ADR-0005: Introduce Versioned Derived Prediction Artifacts](../../architecture/decisions/0005-versioned-derived-prediction-artifacts.md) | records append-only edited artifacts, no active pointer, and this per-version sidecar extension |

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
| 2026-08-21 | Store saves as numbered derived artifacts (`edit_v1`, `edit_v2`, …) | Overwriting `Model.gpkgUrl` would clobber raw model output and provenance. |
| 2026-08-21 | Use PMTiles plus a columnar JSON sidecar for browser rendering | The sampled GeoJSON route is capped and not an editing data path. |
| 2026-08-22 | Fold prediction editing into View Results | Users should review, edit, and download from one map route. |
| 2026-08-22 | Keep no mutable active-version pointer | Readers use explicit query parameters or newest defaults; metadata stays append-only. |
| 2026-08-25 | Add per-version prediction-attribute sidecars | The model-scoped raw sidecar cannot represent edited classes, so each edited GeoPackage needs matching derived class data. |
| 2026-08-25 | Version selection changes the map only | Reports continuing to use newest avoids broad report state management; the accepted trade-off is that the UI must disclose map/report mismatch. |
| 2026-08-25 | Route version downloads through `GetModelArtifact` | Auth, managed identity, Range, and content disposition should stay centralized in the Functions app. |
| 2026-08-25 | Backfill existing version sidecars via the prediction-tiles job | Read handlers must not generate artifacts; dev models `0448` v1 and `5553` v1 require one-time idempotent backfill. |
