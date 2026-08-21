# Test Plan: Prediction Editing

**Contents:** [Test Strategy](#test-strategy) · [Test Scenarios](#test-scenarios) · [Test Data Requirements](#test-data-requirements) · [Coverage Matrix](#coverage-matrix) · [Environment Requirements](#environment-requirements) · [Sign-off Criteria](#sign-off-criteria)

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | `hastegeo` schema detection, class derivation, sidecar generation, row-order preservation, version allocation | pytest / unittest (`hastelib/tests/`) | all core rules and both producer schemas |
| Integration | Prediction edit HTTP endpoints and artifact retrieval | pytest + Azure Functions test harness | success and negative responses; not implemented in current branch |
| Queue | PMTiles and sidecar prep worker | pytest / Docker Compose worker test | idempotent generation and failure handling |
| UI | Edit buttons, route, map state, filters, threshold slider, save flow | Plain Node unit tests for helpers today; browser/Playwright follow-up | critical analyst flows |
| E2E | Full stack with trained and embedding predictions | Docker Compose + manual verification; Playwright unavailable today | one successful version save per workflow |
| Performance | Large layer prep/save/browser memory | custom scripts with representative GeoPackages | no timeout/memory regression beyond agreed thresholds |

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

| ID | Module | Scenario | Input | Expected Output | Story Ref |
|---|---|---|---|---|---|
| UT-001 | `hastegeo/core/models/projects.py` | Model defaults | Model without new fields | `editedPredictions` behaves as empty list; prediction count/timestamps/sidecar/job/status fields nullable/defaulted | US-004 |
| UT-002 | `hastegeo/core/config.py` | Artifact template rendering | `modelId=123`, `version=2`, `imageLayerId=abc` | `edited_predictions_123_v2`, `prediction_attrs_123`, `footprints_abc` | US-002, US-004 |
| UT-003 | `hastegeo/core/utils/predictions.py` | Trained schema detection | GPKG with `damage_pct_0m`, `damage_pct_10m`, `damage_pct_20m`, `damaged`, `unknown_pct` | `flavor="inference"`, `supportsThreshold=true` | US-002 |
| UT-004 | `hastegeo/core/utils/predictions.py` | Embedding schema detection | GPKG layer `predictions` with `area`, `damaged`, degenerate `damage_pct_0m` | `flavor="embedding"`, `supportsThreshold=false` | US-002 |
| UT-005 | `hastegeo/core/processors/prediction_edits.py` | Class derivation without override | damage `0.2`, unknown `0.0`, threshold `0.1` | `Damaged`, `damaged=1` | US-003, US-004 |
| UT-006 | `hastegeo/core/processors/prediction_edits.py` | Unknown wins before damage | damage `0.8`, unknown `0.3`, unknownThreshold `0.0` | `Unknown`, `damaged=0` | US-003, US-004 |
| UT-007 | `hastegeo/core/processors/prediction_edits.py` | Override wins over thresholds | override `NotDamaged`, damage `0.9` | `NotDamaged`, `damaged=0` | US-003, US-004 |
| UT-008 | `hastegeo/core/processors/prediction_edits.py` | Row-order invariant | Footprints ids `[a,b,c]`; predictions rows `[0,1,2]` | Edited rows remain `[0,1,2]` with `overture_id` `[a,b,c]` | US-004 |
| UT-009 | `hastegeo/core/processors/prediction_edits.py` | Row-count mismatch | Footprints 3 rows; predictions 2 rows | Raises validation error; no version metadata appended | US-002, US-004 |
| UT-010 | `hastegeo/core/processors/prediction_edits.py` | Version allocation | Existing versions `[1,2]` | Next artifact uses version `3` | US-004 |
| UT-011 | `hastegeo/workflows/prepare_prediction_tiles.py` | Sidecar shape | Three prediction rows | JSON has `n=3` and same-length `ids`, `overtureIds`, `damage`, `unknown`, `damaged` arrays | US-002 |
| UT-012 | `hastegeo/core/models/predictions.py` | Wire request validation | Save/prep request bodies | Invalid IDs, thresholds, classes, duplicate override IDs rejected before processors run | US-002, US-004 |
| UT-013 | `hastegeo/core/processors/prediction_tiles.py` | Prep request idempotency | Ready, missing, in-flight, and forced model/layer states | Returns `{modelId, queued, tilesReady, attrsReady, status, statusMessage}` and enqueues at most one message | US-002 |

### API Integration Tests

No prediction-editing API integration tests are implemented in the current
branch. `api/hastefuncapi/tests/` contains only `test_publishing_routes.py`; the
cases below remain follow-up coverage.

| ID | Endpoint | Method | Scenario | Preconditions | Expected Response | Story Ref |
|---|---|---|---|---|---|---|
| IT-001 | `/api/GetPredictionEditSession` | GET | Ready trained model | Processed inference model with raw GPKG, PMTiles, sidecar | 200 with `flavor="inference"`, `supportsThreshold=true`, `defaultThreshold=0.0`, readiness flags, and prep status fields | US-002 |
| IT-002 | `/api/GetPredictionEditSession` | GET | Ready embedding model | Embedding model with `gpkgUrl` and `predictedBuildingCount>0` | 200 with `flavor="embedding"`, `supportsThreshold=false` | US-002 |
| IT-003 | `/api/GetPredictionEditSession` | GET | Missing prep artifacts | Raw GPKG exists, PMTiles/sidecar absent | 200 with readiness false and no queued message | US-002 |
| IT-004 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | Queue missing prep | Raw GPKG and building footprints exist; artifacts missing | 200 with `queued=true`, `status="Queued"`, and exactly one queue message | US-002 |
| IT-005 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | Ready no-op | PMTiles and sidecar already exist; `force=false` | 200 with `queued=false`, `tilesReady=true`, `attrsReady=true`, no queue message | US-002 |
| IT-006 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | In-flight no-op | `predictionTilesStatus` is `Queued` or `InProgress`; `force=false` | 200 with `queued=false`, current status, no duplicate queue message | US-002 |
| IT-007 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | Missing source inputs | No `gpkgUrl` or no `buildingFootprintsUrl` | 404 | US-002 |
| IT-008 | `/api/PutEditedPredictions` | PUT | Save first edit | Valid thresholds and overrides | 200 with `version=1`, `gpkgUrl`, `editedCount`; Model gets one version | US-004 |
| IT-009 | `/api/PutEditedPredictions` | PUT | Invalid threshold | `threshold=2` | 400 | US-004 |
| IT-010 | `/api/PutEditedPredictions` | PUT | Override out of range | `id >= buildingCount` | 200; unmatched override ignored and not counted | US-004 |
| IT-011 | `/api/GetEditedPredictionVersions` | GET | Existing versions | Model has versions | 200 with version metadata list, newest first | US-005 |
| IT-012 | `/api/GetModelArtifact` | GET | Fetch new artifact kinds | Prepared PMTiles and sidecar | 200 for `footprint_pmtiles` and JSON `prediction_attrs` | US-002, US-005 |
| IT-013 | `/api/GetPredictionEditSession` | GET | Missing model | Unknown `modelId` | 404 | US-002 |

### Queue Worker Tests

| ID | Queue | Scenario | Message | Expected Side Effect | Story Ref |
|---|---|---|---|---|---|
| QT-001 | `prediction-edit-prep-queue` | Build missing PMTiles and sidecar | valid project/layer/model/source urls | PMTiles and sidecar blobs uploaded; metadata fields updated | US-002 |
| QT-002 | `prediction-edit-prep-queue` | Idempotent no-op | artifacts already exist and `force=false` | No duplicate work; metadata remains consistent | US-002 |
| QT-003 | `prediction-edit-prep-queue` | Force rebuild | artifacts exist and `force=true` | Artifacts regenerated and metadata timestamp refreshed | US-002 |
| QT-004 | `prediction-edit-prep-queue` | Malformed message | neither `modelId` nor `imageLayerId` | Worker logs validation error and dead-letters/fails without partial metadata | US-002 |
| QT-005 | `prediction-edit-prep-queue` | Row-count mismatch | predictions and footprints lengths differ | Prep fails; no `predictedAt` update | US-002 |
| QT-006 | `prediction-edit-prep-queue` | Layer-only prep | empty `modelId`, layer with footprints | PMTiles blob uploaded; only `ImageLayer.footprintPmtilesUrl`/`footprintTiles*` written; no sidecar and no model document touched | US-002 |
| QT-007 | `prediction-edit-prep-queue` | Layer-only no-op | empty `modelId`, layer already has `footprintPmtilesUrl`, `force=false` | No job submitted; layer marked `Processed` | US-002 |
| QT-008 | imagery prep (`ImageryPostProcessor`) | Layer-time scheduling | layer completes with cached footprints and no tiles | Exactly one layer-only message enqueued; none when tiles exist or the footprint step errored; enqueue failure never fails imagery prep | US-002 |

### UI Component Tests

The current branch includes plain Node tests for `predictionClassify.js` and
`predictionPrep.js`. It does not include a React Testing Library, Vitest, or
Playwright harness for browser rendering.

| ID | Component | Scenario | User Action | Expected Behavior | Story Ref |
|---|---|---|---|---|---|
| UI-001 | `ModelResultsButton.jsx` | Trained edit gating | Render model variations | Enabled only when `inferenceStatus === "Processed" && gpkgUrl` | US-001 |
| UI-002 | `EmbeddingModelRow.jsx` | Embedding edit gating | Render model variations | Enabled only when `gpkgUrl && predictedBuildingCount > 0` | US-001 |
| UI-003 | `PredictionEditor.jsx` / `predictionPrep.js` | Prep pending | Load session with `tilesReady=false` | Calls `PutPreparePredictionTilesQueueMessage`, shows preparation state, and polls session | US-002 |
| UI-004 | `PredictionEditor.jsx` / `predictionClassify.js` | Trained threshold | Load `supportsThreshold=true`; move slider | Slider visible; colors and flip counts update | US-003 |
| UI-005 | `PredictionEditor.jsx` | Embedding no threshold | Load `supportsThreshold=false` | Slider hidden; manual overrides available | US-003 |
| UI-006 | `PredictionEditor.jsx` | Click classify | Click footprint and choose class | Feature color and counts update via feature-state | US-003 |
| UI-007 | `PredictionEditor.jsx` | Box-select classify | Ctrl+drag selection and choose class | All selected features update | US-003 |
| UI-008 | `PredictionEditor.jsx` | Save version | Click Save as new version | PUT body includes thresholds and overrides; version list refreshes | US-004, US-005 |
| UI-009 | `PredictionEditorRightPanel.jsx` | Version history | Save or load existing versions | History displays version, timestamp, threshold, editor, and edited count; one-click download remains follow-up | US-005 |
| UI-010 | `PredictionEditor.jsx` | Dark mode | Render in dark theme | Styles use Fluent tokens and remain legible | US-003 |
| UI-011 | `ui/src/util/pmtiles.js` | Shared protocol singleton | Render multiple PMTiles screens | Both screens share one `pmtiles://` protocol instance | US-002, US-003 |

### End-to-End Tests (Docker Compose)

| ID | User Flow | Steps | Expected Outcome | Story Ref |
|---|---|---|---|---|
| E2E-001 | Trained prediction edit | 1. Start Docker Compose 2. Use a processed trained model with `gpkgUrl` 3. Open Edit 4. Wait for prep 5. Change threshold and override one building 6. Save | `edit_v1` GeoPackage downloads; raw `Model.gpkgUrl` unchanged | US-001-US-005 |
| E2E-002 | Embedding prediction edit | 1. Start Docker Compose 2. Use an embedding model with non-empty predictions 3. Open Edit 4. Confirm no threshold slider 5. Override one building 6. Save | `edit_v1` GeoPackage downloads with expected class columns | US-001-US-005 |
| E2E-003 | Empty embedding predictions | 1. Save empty embedding predictions 2. Return to project management | Edit button remains disabled because `predictedBuildingCount` is not positive | US-001 |

### Edge Case & Negative Tests

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| NEG-001 | Unauthenticated API request | No function key / invalid auth context | 401 or existing platform auth failure |
| NEG-002 | Non-existent project ID | Random GUID | 404 |
| NEG-003 | Invalid class | override class `Destroyed` | 400 |
| NEG-004 | Duplicate override ids | two overrides for id `7` | 400 or deterministic client-side collapse before request |
| NEG-005 | Missing raw GPKG | Model lacks `gpkgUrl` | 404 from session; button disabled in UI |
| EDGE-001 | Very large layer | Representative large GeoPackage | Prep/save complete within agreed memory/time budget or produce actionable error |
| EDGE-002 | Concurrent saves | Parallel PUT requests | Known gap: current implementation can allocate the same next version; add optimistic concurrency follow-up |
| EDGE-003 | Threshold default split | Session default vs report default | Editor session remains `0.0`; assessment report default remains `0.1`; product decision is documented |
| EDGE-004 | UI lint baseline | Current repo-wide ESLint 9 flat-config failure | Validation records no regression from baseline, not necessarily clean lint |

### Performance Tests

| ID | Scenario | Load Profile | Target Metric | Threshold |
|---|---|---|---|---|
| PERF-001 | Session readiness | 50 concurrent session requests that read raw prediction GeoPackages for flavor/count | p99 latency | threshold TBD after representative GPKG measurement |
| PERF-002 | PMTiles/sidecar prep | One dense urban layer | job duration and peak memory | fit existing worker/Batch limits; no OOM |
| PERF-003 | Save edited version | GeoPackage at 95th percentile building count | function duration and peak memory | complete below platform timeout or trigger async-save follow-up |
| PERF-004 | Browser editing | PMTiles + sidecar for dense layer | Chrome heap and interaction latency | no tab crash; pan/selection remains usable |

## Test Data Requirements

| Dataset | Description | Source | Sensitive? |
|---|---|---|---|
| Trained inference sample GeoPackage | Includes continuous `damage_pct_0m`, `damage_pct_10m`, `damage_pct_20m`, `damaged`, `unknown_pct` | Synthetic or sanitized existing fixture | no |
| Embedding prediction sample GeoPackage | Layer `predictions`, `area`, `damaged`, degenerate `damage_pct_0m` | Synthetic or sanitized existing fixture | no |
| Source footprints GeoPackage | Ordered Overture ids matching prediction rows | Synthetic | no |
| Large dense footprint set | Stress PMTiles, sidecar, and save memory | Synthetic | no |
| Model/ImageLayer metadata fixtures | Raw and edited model documents | Synthetic | no |

## Coverage Matrix

| User Story | Unit | API Integration | Queue | UI | E2E | Performance |
|---|---|---|---|---|---|---|
| US-001 | — | — | — | UI-001, UI-002 | E2E-001, E2E-002, E2E-003 | — |
| US-002 | UT-003, UT-004, UT-008, UT-009, UT-011, UT-012, UT-013 | IT-001-IT-007, IT-012, IT-013 | QT-001-QT-005 | UI-003, UI-011 | E2E-001, E2E-002 | PERF-001, PERF-002 |
| US-003 | UT-005, UT-006, UT-007 | — | — | UI-004-UI-007, UI-010, UI-011 | E2E-001, E2E-002 | PERF-004 |
| US-004 | UT-001, UT-002, UT-005-UT-010, UT-012 | IT-008-IT-010 | — | UI-008 | E2E-001, E2E-002 | PERF-003 |
| US-005 | UT-001 | IT-011, IT-012 | — | UI-008, UI-009 | E2E-001, E2E-002 | — |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (Docker Compose) | Developer testing of UI, API, queue, Azurite artifacts | `docker/docker-compose.yml`; no prediction-editing feature flags implemented |
| CI (GitHub Actions) | Automated backend and UI tests | Existing secret scan/deploy workflows plus targeted tests |
| Dev1 SWA | Integration testing with realistic project data | Feature flags enabled for internal testers |
| Testing SWA | Pre-production validation | Feature flags enabled after dev1 sign-off |

## Sign-off Criteria

- [ ] All P0 stories have E2E coverage for trained and embedding workflows.
- [ ] Row-order preservation is asserted in unit tests; API integration coverage remains a follow-up.
- [ ] `hastelib` targeted tests pass for prediction editing.
- [ ] API integration tests are added and pass for session, prep, save, version list, and artifact retrieval.
- [ ] UI helper tests pass; browser/Playwright tests are added for gating,
      threshold visibility, selection, save, version history, and dark mode.
- [ ] Performance tests establish safe limits or document a follow-up async-save
      requirement.
- [ ] UI lint validation records no regression from the known repo-wide ESLint 9
      flat-config baseline.
