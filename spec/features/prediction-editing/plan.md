# Execution Plan: Prediction Editing

**Contents:** [Phases](#phases) · [Milestones](#milestones) · [Agent Summary](#agent-summary) · [Resource Requirements](#resource-requirements) · [Open Questions](#open-questions)

## Phases

### Phase 1: Core Library — implemented

**Goal:** Implement core models, artifact naming, schema normalization,
versioned edit writing, readiness, and reader source selection in
`hastelib/src/hastegeo/`.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add `EditedPredictionVersion`, `Model.editedPredictions`, `Model.predictedBuildingCount`, `Model.predictedAt`, `Model.predictionAttrsUrl`, `Model.predictionTilesJob`, `Model.predictionTilesStatus`, `Model.predictionTilesStatusMessage`, and `ImageLayer.footprintPmtilesUrl` | `backend-dev` | — | US-002, US-004 | complete (`hastelib/src/hastegeo/core/models/projects.py:343-505`, `hastelib/src/hastegeo/core/models/projects.py:520-529`, `hastelib/src/hastegeo/core/models/projects.py:842-851`) |
| Add transport-only wire models in `hastelib/src/hastegeo/core/models/predictions.py` | `backend-dev` | model fields | US-002, US-004 | complete |
| Add `EDITED_PREDICTIONS_GPKG`, `PREDICTION_ATTRS`, and `LAYER_FOOTPRINT_PMTILES` artifact types | `backend-dev` | — | US-002, US-004 | complete (`hastelib/src/hastegeo/core/config.py:165-172`) |
| Implement prediction schema detection for trained inference vs embedding outputs in `core/utils/predictions.py` | `backend-dev`, `gis` | model fields | US-002 | complete (`hastelib/src/hastegeo/core/utils/predictions.py:4-34`) |
| Implement row-order validation and Overture id extraction from source footprints | `gis` | schema detection | US-002, US-004 | complete (`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:322-416`) |
| Implement class derivation and edited GeoPackage writer in `core/processors/prediction_edits.py` | `backend-dev`, `gis` | row-order validation | US-004 | complete (`hastelib/src/hastegeo/core/processors/prediction_edits.py:226-308`) |
| Add one server-derived readiness rule in `core/utils/model_readiness.py` | `backend-dev` | model fields | US-001, US-002 | complete (`hastelib/src/hastegeo/core/utils/model_readiness.py:132-237`) |
| Add `resolve_prediction_source(model, version=None)` next to `read_predictions` | `backend-dev` | `Model.editedPredictions` | US-006 | complete (`hastelib/src/hastegeo/core/utils/predictions.py:332-401`) |
| Write unit tests for schema detection, class derivation, version allocation, row-order preservation, readiness, source resolution, and visualizer payload assembly | `backend-dev`, `gis` | all above | US-001, US-002, US-004, US-006 | complete (`hastelib/tests/core/utils/test_model_readiness.py:148-229`, `hastelib/tests/core/utils/test_prediction_source.py:89-188`, `hastelib/tests/core/processors/test_visualizer_payload.py:222-392`) |

> **Agent column:** Use HASTE agent names (`backend-dev`, `gis`, `ui`, `security`). See [user-stories.md](user-stories.md#agent-assignment-map) for the full agent→story mapping.

**Exit Criteria:**
- [x] `hastelib` unit tests cover both producer schemas and row-order preservation.
- [x] Edited GeoPackage generation works independently of the API layer.
- [x] Raw `Model.gpkgUrl` remains unchanged after saves.
- [x] Server readiness and raw-vs-edited source selection are pure helpers with targeted tests.

### Phase 2: API Layer — implemented with known test gaps

**Goal:** Expose prediction editing and vector-first results through thin
`hastefuncapi` routes and a queued preparation worker.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add side-effect-free `GetPredictionEditSession` route | `backend-dev` | Phase 1 models | US-002 | complete (`api/hastefuncapi/function_app.py:2920-3025`) |
| Add `PutPreparePredictionTilesQueueMessage` route for explicit prep queue requests | `backend-dev` | `core/processors/prediction_tiles.py` | US-002 | complete |
| Add `PutEditedPredictions` route | `backend-dev` | edited GeoPackage writer | US-004 | complete (`api/hastefuncapi/function_app.py:3181-3345`) |
| Add `GetEditedPredictionVersions` route | `backend-dev` | Phase 1 models | US-005 | complete (`api/hastefuncapi/function_app.py:3376-3410`) |
| Extend `GetModelArtifact` with `footprint_pmtiles` and `prediction_attrs` kinds | `backend-dev` | artifact types | US-002, US-005 | complete (`api/hastefuncapi/function_app.py:1400-1510`) |
| Add `workflows/prepare_prediction_tiles.py` prep workflow (footprint PMTiles + attribute sidecar) | `gis` | Phase 1 prediction reader | US-002 | complete (`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:4-46`, `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:322-416`) |
| Add `core/processors/prediction_tiles.py` runner orchestration | `gis` | prep workflow | US-002 | complete (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:4-84`, `hastelib/src/hastegeo/core/processors/prediction_tiles.py:475-560`) |
| Add `prediction-edit-prep-queue` trigger in `hastefuncqueues` | `backend-dev`, `gis` | prep workflow | US-002 | complete (`api/hastefuncqueues/function_app.py:861-914`) |
| Build the layer's footprint PMTiles at image-layer creation (layer-only prep mode; `ImageLayer.footprintTiles*` fields; best-effort enqueue from `ImageryPostProcessor`) | `gis` | prep workflow, queue trigger | US-002 | complete (`hastelib/src/hastegeo/core/processors/imagery.py:249-257`, `hastelib/src/hastegeo/core/processors/imagery.py:399-441`) |
| Make `GetVisualizerResults` workflow-agnostic and vector-first (footprint tiles + attrs sidecar as `GetModelArtifact` routes, `predictionsReady`/readiness detail, `flavor`/`supportsThreshold`, nullable raster layers); payload assembly in `core/processors/visualizer.py` | `backend-dev` | `core/processors/prediction_tiles.py`, prediction reader | US-001, US-002, US-006 | complete (`api/hastefuncapi/function_app.py:2296-2435`, `hastelib/src/hastegeo/core/processors/visualizer.py:215-336`) |
| Surface `predictionsReady` on `GetLayerModelsDetails`, `GetProjectDetails`, and `GetLayerDetailView`; reuse the same completion rule in `core/publishing/source.py` | `backend-dev` | `core/utils/model_readiness.py` | US-001 | complete (`api/hastefuncapi/function_app.py:785-788`, `api/hastefuncapi/function_app.py:1262-1266`, `api/hastefuncapi/function_app.py:1380-1383`, `hastelib/src/hastegeo/core/publishing/source.py:116-124`) |
| Adopt `resolve_prediction_source(model, version=None)` and optional `version` query param in `GetVisualizerResults`, `GetValidationReport`, and `GetAssessmentReport` | `backend-dev` | `Model.editedPredictions` | US-006 | complete (`api/hastefuncapi/function_app.py:2386-2435`, `api/hastefuncapi/function_app.py:4677-4688`, `api/hastefuncapi/function_app.py:5017-5027`) |
| Document the full `GetVisualizerResults` shape and reader `version` behavior in the API docs | `backend-dev` | route implementation | US-002, US-006 | complete (`docs/api/hastefuncapi.md:78-157`, `docs/api/hastefuncapi.md:480-502`) |
| Add API integration tests for visualizer payloads, validation, readiness, save, and version-list responses | `backend-dev` | routes | US-002, US-004, US-005, US-006 | not-started |
| Add `infra/modules/functions.bicep` app-setting parity for the new queue | `backend-dev` | queue config | US-002 | skipped — `Config` has a default and changing Bicep without regenerating `infra/main.json` would create infra drift |

**Exit Criteria:**
- [x] Endpoints are implemented as Azure Functions routes.
- [x] Missing PMTiles/sidecars are generated by the queue worker, not inline in HTTP.
- [x] Footprint PMTiles are built once per image layer at layer-creation time; the on-demand path still covers pre-existing layers.
- [x] `PutEditedPredictions` returns `version`, `gpkgUrl`, and `editedCount` for both producer schemas.
- [x] Readers default to the newest edited version and accept an explicit `version` override (no mutable "active version" pointer — see ADR-0005).
- [x] `GetVisualizerResults` returns a usable 200 payload for an embedding model, with the raster fields nullable rather than broken.
- [ ] Docker Compose local stack can exercise session prep and save.
- [ ] API-level integration tests exist for the new and modified routes.

### Phase 3: UI — implemented with validation gaps

**Goal:** Use the existing View Results page as the prediction review and edit
surface with Azure Maps, PMTiles, Fluent UI, and existing HASTE interaction
patterns.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Remove the standalone `/edit-predictions/:projectId/:imageLayerId/:modelId` route and `PredictionEditor` screen; keep only `/visualizer/:projectId/:imageLayerId/:modelId` | `ui` | route component removal | US-001 | complete (`ui/src/Components/AppBody.jsx:73-75`) |
| Remove standalone model-row Edit buttons; make trained model Results → View use `predictionsReady` with a processed-inference fallback | `ui` | API model payload flag | US-001 | complete (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:87-110`) |
| Add embedding View Results as the first Results menu item, gated by `predictionsReady` with a legacy `gpkgUrl` fallback | `ui` | API model payload flag | US-001 | complete (`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:85-130`) |
| Add vector-first predicted-footprint rendering to the Visualizer through `usePredictionArtifacts`, `usePredictionFootprints`, and `predictionFootprintMap.js` | `ui` | `GetVisualizerResults`, `GetModelArtifact` | US-002, US-003 | complete (`ui/src/Components/Visualizer/Visualizer.jsx:166-199`, `ui/src/Components/Visualizer/usePredictionArtifacts.js:177-221`, `ui/src/Components/Visualizer/usePredictionFootprints.js:4-29`) |
| Add status-note handling for loading/preparing/empty/unavailable predicted buildings | `ui` | readiness contract | US-002 | complete (`ui/src/Components/Visualizer/PredictionStatusNote.jsx`, `ui/src/Components/Visualizer/predictionResults.js:320-385`) |
| Add pencil/Done affordance next to Back, `E` shortcut, and unsaved-edits discard confirmation | `ui` | vector footprint readiness | US-001, US-003 | complete (`ui/src/Components/Visualizer/Labels.jsx:117-128`, `ui/src/Components/Visualizer/Visualizer.jsx:496-605`, `ui/src/Components/keyboardShortcuts.js:7-17`) |
| Move the former editor right panel into `Visualizer/PredictionEditPanel.jsx` with filters, counts, edited filter, prev/next traversal, class controls, threshold sliders, save, and read-only version history | `ui` | map selection state | US-003, US-005 | complete (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:4-16`, `ui/src/Components/Visualizer/PredictionEditPanel.jsx:300-585`) |
| Add save-as-new-version action that calls `PutEditedPredictions`, refreshes versions, and resets the unsaved baseline | `ui` | `PutEditedPredictions`, versions API | US-004, US-005 | complete (`ui/src/Components/Visualizer/usePredictionFootprints.js:838-902`, `ui/src/Components/Visualizer/usePredictionArtifacts.js:159-168`) |
| Add active-version readout from `predictionVersion`/`predictionVersions` | `ui` | vector-first payload | US-005, US-006 | complete (`ui/src/Components/Visualizer/predictionResults.js:174-180`, `ui/src/Components/Visualizer/predictionResults.js:231-249`, `ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`) |
| Wire version-history row selection to refetch `GetVisualizerResults?version=N` | `ui` | active-version UI design | US-005, US-006 | not-started — history is read-only and `getVisualizerResults` sends no `version` param (`ui/src/Components/Visualizer/Visualizer.jsx:213-223`) |
| Add one-click edited-version download action in the right panel | `ui` | version history display | US-005 | not-started |
| Add shared PMTiles protocol singleton in `ui/src/util/pmtiles.js` and use it from Visualizer artifact loading | `ui` | PMTiles map sources | US-002, US-003 | complete (`ui/src/Components/Visualizer/usePredictionArtifacts.js:25-32`, `ui/src/Components/Visualizer/usePredictionArtifacts.js:201-212`) |
| Add plain Node unit tests for `predictionClassify.js`, `predictionResults.js`, `predictionPrep.js`, `predictionFootprintMap.js`, and `visualizerSwipe.js` behavior | `ui` | UI helpers | US-001-US-006 | complete (`ui/src/Components/Visualizer/predictionClassify.test.js:388-407`, `ui/src/Components/Visualizer/predictionClassify.test.js:958-1030`, `ui/src/Components/Visualizer/predictionClassify.test.js:1112-1243`) |
| Add browser/Playwright coverage for View Results gating, vector loading, threshold visibility, selection, save flow, and version history | `ui-validation` | UI implementation | US-001, US-003, US-005 | not-started — this repo has no Playwright config or dependency (`ui/package.json:6-15`, `ui/package.json:62-75`) |

**Exit Criteria:**
- [x] Feature is accessible from both model-row workflows through View Results.
- [ ] Edit mode works with PMTiles and sidecar data in local SWA dev.
- [x] UI uses `makeStyles` and Fluent tokens; no hard-coded semantic hex colors in the edit panel/map helpers.
- [ ] UI validation shows no regression from the current lint baseline.
- [ ] Browser/Playwright validation exists for the Visualizer edit mode or is explicitly waived.

### Phase 4: Integration & Deployment — TBD

**Goal:** Validate end-to-end behavior and prepare safe rollout.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Run end-to-end Docker Compose scenario for trained-inference View Results and edit mode | `backend-dev`, `ui`, `gis` | Phases 1-3 | US-001, US-002, US-003, US-004, US-006 | not-started |
| Run end-to-end Docker Compose scenario for embedding View Results and edit mode | `backend-dev`, `ui`, `gis` | Phases 1-3 | US-001, US-002, US-003, US-004, US-006 | not-started |
| Verify versioned downloads and raw `Model.gpkgUrl` immutability | `backend-dev` | Phases 1-3 | US-004, US-005 | not-started |
| Verify `GetValidationReport`, `GetAssessmentReport`, and `GetVisualizerResults` default/newest, explicit version, and `version=0` raw behavior | `backend-dev`, `gis` | Phase 2 | US-006 | not-started |
| Verify Azure monitoring and queue dead-letter visibility | `backend-dev` | Phase 2 | US-002 | not-started |
| Update end-user docs only after behavior is implemented and validated | `ui` | Feature complete | US-001-US-006 | not-started |

**Exit Criteria:**
- [ ] Docker Compose validates both workflows.
- [ ] Targeted backend tests pass.
- [ ] Targeted UI helper tests pass; Playwright coverage is added or explicitly waived.
- [ ] CI passes or has a documented no-regression exception for the known UI lint baseline.
- [ ] Known follow-ups are triaged: UI version switching, API integration tests, browser validation, concurrent-save conflict handling, assessment/report semantics, and producer-side Overture ids.

## Milestones

| Milestone | Date | Deliverable |
|---|---|---|
| Spec approved | TBD | Draft spec and ADR reviewed. |
| Core library done | TBD | Models, artifact types, class derivation, readiness, source resolution, and GeoPackage writer merged. |
| Prep/API done | TBD | Session, save, version list, artifact retrieval, vector-first visualizer, report version params, and queue prep working. |
| Results edit mode done | TBD | View Results entry, vector map, filters, threshold, overrides, version list, and save flow working. |
| Release | TBD | Feature promoted after dev/test validation. |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | 21 | 1, 2, 4 |
| `gis` | 8 | 1, 2, 4 |
| `ui` | 15 | 3, 4 |
| `ui-validation` | 1 | 3 |
| `security` | 0 | —; no new dependency is expected |

## Resource Requirements

- **Agents:** `backend-dev`, `gis`, `ui`, `backend-validation`, and
  `ui-validation`.
- **Azure services:** Existing Cosmos metadata store, Blob Storage, Queue
  Storage, Azure Functions, and existing Batch/runner capacity.
- **GPU compute:** None required for editing or tile generation. The training
  container is used because it contains `tippecanoe`, not because GPU is needed.
- **External data:** None beyond existing project imagery, footprints, and model
  prediction artifacts.

## Open Questions

- [x] Confirm the concrete queue config key name before implementation.
      Resolved: `prediction_edit_prep_queue_name` in `Config.get_queue_config()`
      (env `PREDICTION_EDIT_PREP_QUEUE_NAME`, default `prediction-edit-prep-queue`,
      `local-prediction-edit-prep-queue` in the Docker Compose stack).
- [ ] Decide whether high-volume saves need an async save path after measuring
      real production layer sizes.
- [ ] Decide whether UI version switching should refetch `GetVisualizerResults?version=N`, add a separate version-selection endpoint, or stay read-only.
- [ ] Decide how assessment counts should incorporate per-building overrides when edited GeoPackages preserve the producer's original `damage_pct_0m`.
- [ ] Add optimistic concurrency for simultaneous saves before supporting multi-analyst editing of the same model.
- [ ] Fix or explicitly mitigate the pre-existing positional-join risks: classic inference can drop footprint rows before writing predictions, and neither producer writes an explicit `overture_id` column (`docker/training/code/merge_with_building_footprints.py:151-190`, `docker/training/code/merge_with_building_footprints.py:221-258`, `api/hastefuncapi/function_app.py:2738-2815`).
