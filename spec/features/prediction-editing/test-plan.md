# Test Plan: Prediction Editing

**Contents:** [Test Strategy](#test-strategy) · [Test Scenarios](#test-scenarios) · [Test Data Requirements](#test-data-requirements) · [Coverage Matrix](#coverage-matrix) · [Environment Requirements](#environment-requirements) · [Sign-off Criteria](#sign-off-criteria)

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | `hastegeo` readiness, source resolution, schema detection, class derivation, sidecar generation, row-order preservation, and version allocation | pytest / unittest (`hastelib/tests/`) | all core rules, both producer schemas, and raw/newest/explicit version selection |
| Integration | `GetVisualizerResults`, prediction edit/prep/version HTTP endpoints, artifact retrieval, and report `version` query handling | pytest + Azure Functions test harness | success and negative responses; API-level tests for the rewritten handler are not implemented in the current branch |
| Queue | PMTiles and sidecar prep worker | pytest / Docker Compose worker test | idempotent generation, layer-only prep, model prep, and failure handling |
| UI | Existing Visualizer route, vector layer loading, edit-mode entry/exit, keyboard shortcut, discard confirmation, save flow, and read-only version history | Plain Node unit tests for helper modules today; browser/Playwright follow-up | critical analyst flows without a standalone editor screen |
| E2E | Full stack with trained and embedding predictions | Docker Compose + manual verification; Playwright unavailable today | View Results works for both workflows and at least one edited version can be saved |
| Performance | Large layer prep/save/browser memory | custom scripts with representative GeoPackages | no timeout/memory regression beyond agreed thresholds |

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

| ID | Module | Scenario | Input | Expected Output | Story Ref |
|---|---|---|---|---|---|
| UT-001 | `hastegeo/core/models/projects.py` | Model defaults | Model without optional prediction fields | `editedPredictions` behaves as empty list; prediction count/timestamps/sidecar/job/status fields nullable/defaulted | US-004, US-005 |
| UT-002 | `hastegeo/core/config.py` | Artifact template rendering | `modelId=123`, `version=2`, `imageLayerId=abc` | `edited_predictions_123_v2`, `prediction_attrs_123`, `footprints_abc` | US-002, US-004 |
| UT-003 | `hastegeo/core/utils/model_readiness.py` | Unified model-row readiness | Inference, embedding, empty, clear-label, and missing-artifact model states | One `predictionsReady` result and reason contract is applied across model payloads and publishing (`hastelib/src/hastegeo/core/utils/model_readiness.py:132-237`) | US-001, US-002 |
| UT-004 | `hastegeo/core/utils/predictions.py` | Source resolution | No `version`, `version=0`, explicit edited version, missing version | Defaults to newest edited version; `version=0` returns raw output; explicit version returns that edit or raises not found (`hastelib/src/hastegeo/core/utils/predictions.py:332-401`) | US-006 |
| UT-005 | `hastegeo/core/utils/predictions.py` | Trained schema detection | GPKG with `damage_pct_0m`, `damage_pct_10m`, `damage_pct_20m`, `damaged`, `unknown_pct` | `flavor="inference"`, `supportsThreshold=true` | US-002, US-003 |
| UT-006 | `hastegeo/core/utils/predictions.py` | Embedding schema detection | GPKG layer `predictions` with `area`, `damaged`, degenerate `damage_pct_0m` | `flavor="embedding"`, `supportsThreshold=false` | US-002, US-003 |
| UT-007 | `hastegeo/core/processors/prediction_edits.py` | Class derivation without override | damage `0.2`, unknown `0.0`, threshold `0.1` | `Damaged`, `damaged=1` | US-003, US-004 |
| UT-008 | `hastegeo/core/processors/prediction_edits.py` | Unknown wins before damage | damage `0.8`, unknown `0.3`, unknownThreshold `0.0` | `Unknown`, `damaged=0` | US-003, US-004 |
| UT-009 | `hastegeo/core/processors/prediction_edits.py` | Override wins over thresholds | override `NotDamaged`, damage `0.9` | `NotDamaged`, `damaged=0` | US-003, US-004 |
| UT-010 | `hastegeo/core/processors/prediction_edits.py` | Row-order invariant | Footprints ids `[a,b,c]`; predictions rows `[0,1,2]` | Edited rows remain `[0,1,2]` with `overture_id` `[a,b,c]` | US-004 |
| UT-011 | `hastegeo/core/processors/prediction_edits.py` | Row-count mismatch | Footprints 3 rows; predictions 2 rows | Raises validation error; no version metadata appended | US-002, US-004 |
| UT-012 | `hastegeo/core/processors/prediction_edits.py` | Version allocation | Existing versions `[1,2]` | Next artifact uses version `3`; concurrent-save conflict is a known follow-up, not expected here | US-004, US-005 |
| UT-013 | `hastegeo/workflows/prepare_prediction_tiles.py` | Sidecar shape | Three prediction rows | JSON has `n=3` and same-length `ids`, `overtureIds`, `damage`, `unknown`, `damaged` arrays | US-002 |
| UT-014 | `hastegeo/core/models/predictions.py` | Wire request validation | Save/prep request bodies | Invalid IDs, thresholds, classes, duplicate override IDs rejected before processors run | US-002, US-004 |
| UT-015 | `hastegeo/core/processors/prediction_tiles.py` | Prep request idempotency | Ready, missing, in-flight, forced model, and layer-only states | Returns `{modelId, queued, tilesReady, attrsReady, status, statusMessage}` and enqueues at most one message | US-002 |

### API Integration Tests

No prediction-editing API integration tests are implemented in the current
branch. `api/hastefuncapi/tests/` contains only publishing-route coverage; the
cases below remain follow-up coverage for the rewritten handlers.

| ID | Endpoint | Method | Scenario | Preconditions | Expected Response | Story Ref |
|---|---|---|---|---|---|---|
| IT-001 | `/api/GetVisualizerResults` | GET | Ready trained model | Processed inference model with raw GPKG, footprint PMTiles, and sidecar | 200 with `footprintTilesUrl`, `predictionAttrsUrl`, readiness object, `flavor="inference"`, `supportsThreshold=true`, `predictionVersion`, `predictionVersions`, and nullable raster fields as documented (`docs/api/hastefuncapi.md:78-157`) | US-002, US-006 |
| IT-002 | `/api/GetVisualizerResults` | GET | Ready embedding model | Embedding model with `gpkgUrl`, PMTiles, sidecar, and `predictedBuildingCount>0` | 200 with vector fields, `flavor="embedding"`, `supportsThreshold=false`, and no required classic rasters | US-001, US-002 |
| IT-003 | `/api/GetVisualizerResults` | GET | Explicit raw version | Model with edited versions; query `version=0` | Payload reports raw source version and raw building count/readiness | US-006 |
| IT-004 | `/api/GetVisualizerResults` | GET | Explicit edited version | Model with version `2`; query `version=2` | Payload reports `predictionVersion=2` and selects the edited GeoPackage | US-006 |
| IT-005 | `/api/GetVisualizerResults` | GET | Missing prep artifacts | Raw GPKG exists, PMTiles/sidecar absent | 200 with readiness false, null vector URLs as applicable, and `predictionsReadiness` reason | US-002 |
| IT-006 | `/api/GetPredictionEditSession` | GET | Ready trained model | Processed inference model with raw GPKG, PMTiles, sidecar | 200 with `flavor="inference"`, `supportsThreshold=true`, `defaultThreshold=0.0`, readiness flags, and prep status fields | US-002, US-003 |
| IT-007 | `/api/GetPredictionEditSession` | GET | Ready embedding model | Embedding model with `gpkgUrl` and `predictedBuildingCount>0` | 200 with `flavor="embedding"`, `supportsThreshold=false` | US-002, US-003 |
| IT-008 | `/api/GetPredictionEditSession` | GET | Missing prep artifacts | Raw GPKG exists, PMTiles/sidecar absent | 200 with readiness false and no queued message | US-002 |
| IT-009 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | Queue missing prep | Raw GPKG and building footprints exist; artifacts missing | 200 with `queued=true`, `status="Queued"`, and exactly one queue message | US-002 |
| IT-010 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | Ready no-op | PMTiles and sidecar already exist; `force=false` | 200 with `queued=false`, `tilesReady=true`, `attrsReady=true`, no queue message | US-002 |
| IT-011 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | In-flight no-op | `predictionTilesStatus` is `Queued` or `InProgress`; `force=false` | 200 with `queued=false`, current status, no duplicate queue message | US-002 |
| IT-012 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | Missing source inputs | No `gpkgUrl` or no `buildingFootprintsUrl` | 404 | US-002 |
| IT-013 | `/api/PutEditedPredictions` | PUT | Save first edit | Valid thresholds and overrides from Visualizer edit mode | 200 with `version=1`, `gpkgUrl`, `editedCount`; Model gets one version | US-004 |
| IT-014 | `/api/PutEditedPredictions` | PUT | Invalid threshold | `threshold=2` | 400 | US-004 |
| IT-015 | `/api/PutEditedPredictions` | PUT | Override out of range | `id >= buildingCount` | 200; unmatched override ignored and not counted | US-004 |
| IT-016 | `/api/GetEditedPredictionVersions` | GET | Existing versions | Model has versions | 200 with version metadata list, newest first | US-005 |
| IT-017 | `/api/GetModelArtifact` | GET | Fetch new artifact kinds | Prepared PMTiles and sidecar | 200 for `footprint_pmtiles` and JSON `prediction_attrs` | US-002, US-005 |
| IT-018 | `/api/GetValidationReport` | GET | Edited version selected by default | Model has edited version whose `damaged` differs from raw | Default response reflects newest edit; `version=0` restores raw (`api/hastefuncapi/function_app.py:4607-4688`) | US-006 |
| IT-019 | `/api/GetAssessmentReport` | GET | Edited version selected by default | Model has edited version whose `damaged` differs but `damage_pct_0m` is preserved | Default reader opens newest edit, but thresholded counts remain tied to `damage_pct_0m`; this asymmetry is documented (`api/hastefuncapi/function_app.py:4929-5027`) | US-006 |
| IT-020 | `/api/GetPredictionEditSession` | GET | Missing model | Unknown `modelId` | 404 | US-002 |

### Queue Worker Tests

| ID | Queue | Scenario | Message | Expected Side Effect | Story Ref |
|---|---|---|---|---|---|
| QT-001 | `prediction-edit-prep-queue` | Build missing PMTiles and sidecar | valid project/layer/model/source urls | PMTiles and sidecar blobs uploaded; metadata fields updated | US-002 |
| QT-002 | `prediction-edit-prep-queue` | Idempotent no-op | artifacts already exist and `force=false` | No duplicate work; metadata remains consistent | US-002 |
| QT-003 | `prediction-edit-prep-queue` | Force rebuild | artifacts exist and `force=true` | Artifacts regenerated and metadata timestamp refreshed | US-002 |
| QT-004 | `prediction-edit-prep-queue` | Malformed message | neither `modelId` nor `imageLayerId` | Worker logs validation error and fails without partial metadata | US-002 |
| QT-005 | `prediction-edit-prep-queue` | Row-count mismatch | predictions and footprints lengths differ | Prep fails; no `predictedAt` update | US-002 |
| QT-006 | `prediction-edit-prep-queue` | Layer-only prep | empty `modelId`, layer with footprints | PMTiles blob uploaded; only `ImageLayer.footprintPmtilesUrl`/`footprintTiles*` written; no sidecar and no model document touched | US-002 |
| QT-007 | `prediction-edit-prep-queue` | Layer-only no-op | empty `modelId`, layer already has `footprintPmtilesUrl`, `force=false` | No job submitted; layer marked `Processed` | US-002 |
| QT-008 | imagery prep (`ImageryPostProcessor`) | Layer-time scheduling | layer completes with cached footprints and no tiles | Exactly one layer-only message enqueued; none when tiles exist or the footprint step errored; enqueue failure never fails imagery prep | US-002 |

### UI Component Tests

The current branch includes plain Node helper tests, but it does not include a
React Testing Library, Vitest, or Playwright harness for browser rendering. UI
coverage below is therefore a required follow-up before release sign-off.

| ID | Component | Scenario | User Action | Expected Behavior | Story Ref |
|---|---|---|---|---|---|
| UI-001 | `ModelResultsButton.jsx` | Trained results gating | Render model variations | Results menu follows server-derived `predictionsReady` with legacy fallback (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:87-110`) | US-001 |
| UI-002 | `EmbeddingModelRow.jsx` | Embedding View Results | Open Results menu for ready and unready embedding models | First menu item navigates to `/visualizer/...` only when `predictionsReady` is true (`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:85-130`) | US-001 |
| UI-003 | `Visualizer.jsx` | Vector-first load | Open `/visualizer/:projectId/:imageLayerId/:modelId` | Fetches visualizer payload and loads footprint PMTiles plus prediction attrs before edit mode (`ui/src/Components/Visualizer/Visualizer.jsx:457-605`) | US-002 |
| UI-004 | `Labels.jsx` / `Visualizer.jsx` | Enter edit mode | Click pencil next to Back or press `E` | Existing visualizer switches to edit mode; no route change or standalone screen (`ui/src/Components/Visualizer/Labels.jsx:117-128`, `ui/src/Components/Visualizer/Visualizer.jsx:873-921`) | US-003 |
| UI-005 | `Visualizer.jsx` | Leave clean edit mode | Click Done or press `E` with no unsaved edits | Edit controls disappear; vectors remain visible on the View Results page | US-003 |
| UI-006 | `Visualizer.jsx` | Discard confirmation | Press `E`, Back, or Done with unsaved edits | Confirmation dialog appears; cancel keeps edits; discard exits mode | US-003 |
| UI-007 | `PredictionEditPanel.jsx` / `predictionResults.js` | Trained threshold | Load `supportsThreshold=true`; move slider | Slider visible; colors and flip counts update | US-003 |
| UI-008 | `PredictionEditPanel.jsx` | Embedding no threshold | Load `supportsThreshold=false` | Slider hidden; manual overrides available | US-003 |
| UI-009 | `Visualizer.jsx` | Click classify | Click footprint and choose class | Feature color and counts update via vector state | US-003 |
| UI-010 | `Visualizer.jsx` | Box-select classify | Ctrl+drag selection and choose class | All selected features update | US-003 |
| UI-011 | `PredictionEditPanel.jsx` | Save version | Click Save | PUT body includes thresholds and overrides; version list refreshes; raw route stays on `/visualizer/...` | US-004, US-005 |
| UI-012 | `PredictionEditPanel.jsx` | Version history read-only | Load existing versions or save a version | History displays version, timestamp, threshold, editor, edited count, and which version is mapped; selecting another version does not refetch in this branch (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`) | US-005 |
| UI-013 | `Visualizer.jsx` | Dark mode | Render in dark theme | Styles use Fluent tokens and remain legible | US-003 |
| UI-014 | `ui/src/util/pmtiles.js` | Shared protocol singleton | Render multiple PMTiles screens | Both screens share one `pmtiles://` protocol instance | US-002, US-003 |

### End-to-End Tests (Docker Compose)

| ID | User Flow | Steps | Expected Outcome | Story Ref |
|---|---|---|---|---|
| E2E-001 | Trained View Results and edit mode | 1. Start Docker Compose 2. Use a processed trained model with `predictionsReady=true` 3. Open Results → View Results 4. Confirm vector footprints render 5. Enter edit mode with pencil or `E` 6. Change threshold/override one building 7. Save | `edit_v1` GeoPackage downloads; raw `Model.gpkgUrl` unchanged; visualizer payload defaults to newest edit after refresh | US-001-US-006 |
| E2E-002 | Embedding View Results and edit mode | 1. Start Docker Compose 2. Use an embedding model with non-empty predictions 3. Open Results → View Results 4. Confirm vector footprints render and no threshold slider 5. Override one building 6. Save | `edit_v1` GeoPackage downloads with expected class columns; embedding View Results uses `/visualizer/...` | US-001-US-006 |
| E2E-003 | Empty embedding predictions | 1. Save empty embedding predictions 2. Return to project management | Results View remains disabled because server-derived `predictionsReady` is false with `no_buildings` readiness reason | US-001, US-002 |
| E2E-004 | Unsaved edit discard | 1. Enter edit mode 2. Modify one building 3. Press `E` or Done 4. Cancel and then discard | Dialog protects unsaved edits; discard returns to normal visualizer mode | US-003 |
| E2E-005 | Report reader versions | 1. Save edited version 2. Request validation and assessment reports with default, `version=0`, and explicit version | Validation metrics follow edited `damaged`; assessment opens the requested GeoPackage but counts still threshold `damage_pct_0m` | US-006 |

### Edge Case & Negative Tests

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| NEG-001 | Unauthenticated API request | No function key / invalid auth context | 401 or existing platform auth failure |
| NEG-002 | Non-existent project ID | Random GUID | 404 |
| NEG-003 | Invalid class | override class `Destroyed` | 400 |
| NEG-004 | Duplicate override ids | two overrides for id `7` | 400 or deterministic client-side collapse before request |
| NEG-005 | Missing raw GPKG | Model lacks `gpkgUrl` | 404 from edit session; Results disabled in UI through readiness |
| EDGE-001 | Very large layer | Representative large GeoPackage | Prep/save complete within agreed memory/time budget or produce actionable error |
| EDGE-002 | Concurrent saves | Parallel PUT requests | Known gap: current implementation can allocate the same next version; add optimistic concurrency follow-up |
| EDGE-003 | Threshold default split | Session default vs report default | Editor session remains `0.0`; assessment report default remains `0.1`; product decision is documented |
| EDGE-004 | UI lint baseline | Current repo-wide ESLint 9 flat-config failure | Validation records no regression from baseline, not necessarily clean lint |
| EDGE-005 | Version switching | User clicks an older version in the history | Known gap: history is read-only; payload reports current version but selection does not refetch |
| EDGE-006 | Classic footprint row loss | Prediction GPKG has fewer rows than source footprints | Prep/save should fail loudly; producer-side fix remains a follow-up |
| EDGE-007 | Raw Overture id absence | Raw prediction GeoPackage has no explicit `overture_id` | Prep/save relies on positional join today; explicit producer column remains a follow-up |

### Performance Tests

| ID | Scenario | Load Profile | Target Metric | Threshold |
|---|---|---|---|---|
| PERF-001 | Visualizer payload readiness | 50 concurrent `GetVisualizerResults` requests that read selected prediction GeoPackages for flavor/count | p99 latency | threshold TBD after representative GPKG measurement |
| PERF-002 | PMTiles/sidecar prep | One dense urban layer | job duration and peak memory | fit existing worker/Batch limits; no OOM |
| PERF-003 | Save edited version | GeoPackage at 95th percentile building count | function duration and peak memory | complete below platform timeout or trigger async-save follow-up |
| PERF-004 | Browser editing | PMTiles + sidecar for dense layer | Chrome heap and interaction latency | no tab crash; pan/selection remains usable |

## Test Data Requirements

| Dataset | Description | Source | Sensitive? |
|---|---|---|---|
| Trained inference sample GeoPackage | Includes continuous `damage_pct_0m`, `damage_pct_10m`, `damage_pct_20m`, `damaged`, `unknown_pct` | Synthetic or sanitized existing fixture | no |
| Embedding prediction sample GeoPackage | Layer `predictions`, `area`, `damaged`, degenerate `damage_pct_0m` | Synthetic or sanitized existing fixture | no |
| Source footprints GeoPackage | Ordered Overture ids matching prediction rows | Synthetic | no |
| Layer footprint PMTiles | Building geometry artifact independent of a model | Synthetic or generated by prep worker | no |
| Prediction attribute sidecar | Model-scoped arrays matching PMTiles feature ids | Synthetic or generated by prep worker | no |
| Edited prediction GeoPackages | Raw plus `edit_v1` and `edit_v2` documents | Synthetic | no |
| Large dense footprint set | Stress PMTiles, sidecar, and save memory | Synthetic | no |
| Model/ImageLayer metadata fixtures | Raw, unready, ready, and edited model documents | Synthetic | no |

## Coverage Matrix

| User Story | Unit | API Integration | Queue | UI | E2E | Performance |
|---|---|---|---|---|---|---|
| US-001 | UT-003 | IT-002 | — | UI-001, UI-002 | E2E-001, E2E-002, E2E-003 | — |
| US-002 | UT-002, UT-003, UT-005, UT-006, UT-010, UT-011, UT-013, UT-014, UT-015 | IT-001-IT-012, IT-017, IT-020 | QT-001-QT-008 | UI-003, UI-014 | E2E-001, E2E-002, E2E-003 | PERF-001, PERF-002 |
| US-003 | UT-005-UT-009 | — | — | UI-004-UI-010, UI-013, UI-014 | E2E-001, E2E-002, E2E-004 | PERF-004 |
| US-004 | UT-001, UT-002, UT-007-UT-012, UT-014 | IT-013-IT-015 | — | UI-011 | E2E-001, E2E-002 | PERF-003 |
| US-005 | UT-001 | IT-016, IT-017 | — | UI-011, UI-012 | E2E-001, E2E-002 | — |
| US-006 | UT-004 | IT-001, IT-003, IT-004, IT-018, IT-019 | — | UI-012 | E2E-001, E2E-005 | — |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (Docker Compose) | Developer testing of UI, API, queue, Azurite artifacts | `docker/docker-compose.yml`; no prediction-editing feature flags implemented |
| CI (GitHub Actions) | Automated backend and UI tests | Existing secret scan/deploy workflows plus targeted tests |
| Dev1 SWA | Integration testing with realistic project data | Internal testers use existing route and auth; no runtime feature flag |
| Testing SWA | Pre-production validation | Promote after dev1 sign-off; no runtime feature flag |

## Sign-off Criteria

- [ ] All P0 stories have E2E coverage for trained and embedding workflows.
- [ ] Row-order preservation is asserted in unit tests; producer-side row loss and missing raw `overture_id` are tracked as follow-ups.
- [ ] `hastelib` targeted tests pass for readiness, source resolution, prep, and edit processors.
- [ ] API integration tests are added and pass for visualizer payloads, session, prep, save, version list, artifact retrieval, validation report, and assessment report version handling.
- [ ] UI helper tests pass; browser/Playwright tests are added for gating,
      vector-first rendering, edit-mode entry/exit, discard confirmation,
      threshold visibility, selection, save, read-only version history, and dark
      mode.
- [ ] Performance tests establish safe limits or document a follow-up async-save
      requirement.
- [ ] UI lint validation records no regression from the known repo-wide ESLint 9
      flat-config baseline.
