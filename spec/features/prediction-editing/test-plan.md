# Test Plan: Prediction Editing

**Contents:** [Test Strategy](#test-strategy) · [Test Scenarios](#test-scenarios) · [Test Data Requirements](#test-data-requirements) · [Coverage Matrix](#coverage-matrix) · [Environment Requirements](#environment-requirements) · [Sign-off Criteria](#sign-off-criteria)

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | sidecar generation, artifact template rendering, source resolution, save consistency, backfill skip/build | pytest / unittest (`hastelib/tests/`) | raw and edited sidecars agree with their GeoPackages |
| Integration | `GetVisualizerResults`, `GetModelArtifact`, save, backfill queue, and reports | pytest + Azure Functions test harness | version success and negative responses; report default split |
| Queue | prediction-tiles prep and edited-version sidecar backfill | pytest / Docker Compose worker test | idempotent generation and failure handling |
| UI | selector, disabled versions, map-only warning, downloads, dual-pane switching | existing plain Node helper tests plus manual/browser evidence | critical analyst flows without Playwright |
| E2E | full stack trained and embedding predictions | Docker Compose + manual verification | map selection, downloads, and backfill work for representative data |
| Performance | large layer save/backfill/browser memory | custom scripts with representative GeoPackages | no timeout/memory regression beyond agreed thresholds |

No Playwright coverage is available in the current repo: `ui/package.json` has no
Playwright script or dependency (`ui/package.json:6-15`, `ui/package.json:62-75`).
Do not imply browser automation is solved unless that configuration is added.

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

| ID | Module | Scenario | Input | Expected Output | Story Ref |
|---|---|---|---|---|---|
| UT-001 | `core/models/projects.py` | Version metadata schema | Edited version with GPKG and sidecar URLs | `EditedPredictionVersion` stores `gpkgUrl` and `predictionAttrsUrl` without changing `Model.gpkgUrl` | US-004 |
| UT-002 | `core/config.py` | Artifact template rendering | `modelId=5553`, `version=2` | `edited_predictions_5553_v2` and `prediction_attrs_5553_v2`; raw sidecar remains `prediction_attrs_5553` | US-004, US-005 |
| UT-003 | `core/utils/prediction_attrs.py` | Raw sidecar shape | Raw prediction GPKG + matching footprints | JSON arrays have equal length/order and expected `damaged` values | US-002 |
| UT-004 | `core/utils/prediction_attrs.py` | Edited sidecar shape | Edited GPKG with overrides | Sidecar `damaged` and class inputs reflect edited rows, not raw rows | US-004, US-005 |
| UT-005 | `core/utils/prediction_attrs.py` | Row-count mismatch | Predictions and footprints differ | Raises validation error; no sidecar written | US-002, US-004 |
| UT-006 | `core/utils/predictions.py` | Source resolution | No `version`, `version=0`, explicit edited version, missing version | Newest/raw/explicit behavior remains correct; unknown positive version raises not found | US-006 |
| UT-007 | `core/processors/prediction_edits.py` | Save consistency | Overrides and thresholds | Store helper returns both GPKG URL and versioned sidecar URL | US-004 |
| UT-008 | `core/processors/prediction_edits.py` | Sidecar failure | Simulated sidecar upload failure | Version metadata is not appended/advertised | US-004 |
| UT-009 | `core/processors/prediction_tiles.py` | Backfill builds missing sidecar | Edited version has `gpkgUrl` and no `predictionAttrsUrl` | Writes `prediction_attrs_${modelId}_v${version}` and updates metadata | US-008 |
| UT-010 | `core/processors/prediction_tiles.py` | Backfill idempotent skip | Version already has sidecar and `force=false` | No rebuild; metadata unchanged | US-008 |
| UT-011 | `core/processors/visualizer.py` | Versioned artifact URL | Selected raw, v1, v2 | `predictionAttrsUrl` includes the selected version query; `isNewestPredictionVersion` is correct | US-005 |
| UT-012 | `core/processors/visualizer.py` | Report split metadata | Map selected v2 while v3 exists | Payload supports UI warning without changing reports | US-005, US-006 |

### API Integration Tests

| ID | Endpoint | Method | Scenario | Preconditions | Expected Response | Story Ref |
|---|---|---|---|---|---|---|
| IT-001 | `/api/GetVisualizerResults` | GET | Default newest map | Model has raw and versions 1, 2 | 200 selects version 2 and returns version 2 sidecar URL | US-005 |
| IT-002 | `/api/GetVisualizerResults` | GET | Explicit raw map | Query `version=0` | 200 uses raw `Model.predictionAttrsUrl`; newest flag false when edits exist | US-005 |
| IT-003 | `/api/GetVisualizerResults` | GET | Explicit older map | Query `version=1` and version 2 exists | 200 uses v1 sidecar; `isNewestPredictionVersion=false` | US-005, US-006 |
| IT-004 | `/api/GetVisualizerResults` | GET | Unknown version | Query `version=99` | 404 | US-005 |
| IT-005 | `/api/GetVisualizerResults` | GET | Malformed version | Query `version=abc` | 400 | US-005 |
| IT-006 | `/api/GetVisualizerResults` | GET | Missing sidecar | Version has GPKG but no `predictionAttrsUrl` | Payload lists version as disabled/unready or route returns documented non-selectable state | US-005, US-008 |
| IT-007 | `/api/GetModelArtifact` | GET | Raw GPKG download | `kind=gpkg&version=0` | 200 attachment from raw `Model.gpkgUrl` | US-007 |
| IT-008 | `/api/GetModelArtifact` | GET | Edited GPKG download | `kind=gpkg&version=2` | 200 attachment from `EditedPredictionVersion.gpkgUrl` | US-007 |
| IT-009 | `/api/GetModelArtifact` | GET | Raw attrs download | `kind=prediction_attrs&version=0` | 200 JSON from raw `Model.predictionAttrsUrl` | US-005 |
| IT-010 | `/api/GetModelArtifact` | GET | Edited attrs download | `kind=prediction_attrs&version=2` | 200 JSON from `EditedPredictionVersion.predictionAttrsUrl` | US-005, US-007 |
| IT-011 | `/api/GetModelArtifact` | GET | Missing edited sidecar | Version lacks sidecar URL | 404; no lazy generation | US-005, US-008 |
| IT-012 | `/api/PutEditedPredictions` | PUT | Save first new version | Valid overrides | 200 returns `version`, `gpkgUrl`, `predictionAttrsUrl`, `editedCount`; model stores both URLs | US-004 |
| IT-013 | `/api/PutEditedPredictions` | PUT | Sidecar generation failure | Mock helper failure | 500 or documented failure; version not appended | US-004 |
| IT-014 | `/api/PutPreparePredictionTilesQueueMessage` | PUT | Backfill missing versions | `backfillVersions=true` | Queues/executes backfill and skips ready versions | US-008 |
| IT-015 | `/api/GetValidationReport` | GET | Selector map v1, report default | Model has versions 1 and 2 | Report default uses version 2 because UI does not pass selector version | US-006 |
| IT-016 | `/api/GetAssessmentReport` | GET | Preserved fraction gap | Edited `damaged` differs but `damage_pct_0m` preserved | Endpoint opens selected/default GPKG, but threshold counts remain tied to `damage_pct_0m` | US-006 |

### Queue Worker Tests

| ID | Queue | Scenario | Message | Expected Side Effect | Story Ref |
|---|---|---|---|---|---|
| QT-001 | `prediction-edit-prep-queue` | Backfill dev model 0448 | model `0448`, version 1 missing sidecar | Sidecar uploaded and metadata updated, or visible failure status | US-008 |
| QT-002 | `prediction-edit-prep-queue` | Backfill dev model 5553 | model `5553`, version 1 missing sidecar | Sidecar uploaded and metadata updated, or visible failure status | US-008 |
| QT-003 | `prediction-edit-prep-queue` | Idempotent no-op | all versions already have sidecars | No duplicate artifact writes when `force=false` | US-008 |
| QT-004 | `prediction-edit-prep-queue` | Force rebuild | version has sidecar and `force=true` | Sidecar regenerated and metadata refreshed | US-008 |
| QT-005 | `prediction-edit-prep-queue` | Row-count mismatch | edited GPKG and footprints differ | Backfill fails visibly; old metadata not replaced | US-008 |

### UI Component Tests

Current automated UI coverage is helper-level only. Browser behavior must be
validated manually or with new tooling before release.

| ID | Component | Scenario | User Action | Expected Behavior | Story Ref |
|---|---|---|---|---|---|
| UI-001 | Version selector | Default latest | Open View Results with versions | Selector shows latest; map loads latest sidecar | US-005 |
| UI-002 | Version selector | Select raw | Choose Raw | Calls `GetVisualizerResults?version=0`; warning says reports still use newest when edits exist | US-005, US-006 |
| UI-003 | Version selector | Select older edit | Choose version 1 while version 2 exists | Calls `GetVisualizerResults?version=1`; warning appears | US-005, US-006 |
| UI-004 | Version selector | Missing sidecar | Open list with version lacking `predictionAttrsUrl` | Option is disabled and explains backfill is pending | US-005, US-008 |
| UI-005 | Visualizer map | Dual-pane switch | Change selected version | Both swipe panes update colors and no pane keeps stale feature-state | US-003, US-005 |
| UI-006 | Selector download | Download selected | Click download beside selector | Uses `GetModelArtifact?kind=gpkg&version=<selected>` | US-007 |
| UI-007 | Edit panel | Per-row download | Click a version row download | Downloads that row's GPKG through `GetModelArtifact` | US-007 |
| UI-008 | Report buttons | Map-only split | Map on raw/older | Report action copy states reports use newest; request does not include selector version | US-006 |
| UI-009 | Save flow | Save new version | Click Save | Version list refreshes with sidecar URL and saved baseline resets | US-004 |

### End-to-End Tests (Docker Compose)

| ID | User Flow | Steps | Expected Outcome | Story Ref |
|---|---|---|---|---|
| E2E-001 | Trained version selection | 1. Start stack 2. Open trained model View Results 3. Save two versions 4. Select raw, v1, v2 | Map changes to each selected sidecar; reports still default newest; raw `Model.gpkgUrl` unchanged | US-001-US-007 |
| E2E-002 | Embedding version selection | 1. Open embedding model 2. Save version 3. Select raw and v1 | Selector works; threshold slider remains hidden; downloads use API route | US-001-US-007 |
| E2E-003 | Backfill window | 1. Seed edited version without sidecar 2. Open View Results 3. Run backfill | Version is disabled before backfill and selectable after sidecar URL appears | US-005, US-008 |
| E2E-004 | Version downloads | 1. Select v1 2. Download selected 3. Download v2 row | Downloaded files match requested versions | US-007 |
| E2E-005 | Assessment gap | 1. Save override that changes `damaged` only 2. Run reports | Validation changes; Assessment counts do not move with override because `damage_pct_0m` is preserved | US-006 |

### Edge Case & Negative Tests

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| NEG-001 | Unknown version selected | `version=99` | 404 from API; UI shows unavailable state. |
| NEG-002 | Malformed version selected | `version=abc` | 400 from API; UI shows error. |
| NEG-003 | Missing sidecar download | `kind=prediction_attrs&version=1` without sidecar | 404; no generation in GET. |
| NEG-004 | Direct URL fallback | Version download after API 404 | UI does not fall back to raw blob/SAS URL. |
| NEG-005 | Concurrent saves | Parallel PUT requests | Known gap: no 409; document behavior and follow-up. |
| EDGE-001 | Partial swipe switch | Switch while both panes mounted | Both panes repaint from same selected sidecar. |
| EDGE-002 | Backfill rerun | Run backfill twice | Second run skips ready sidecars. |
| EDGE-003 | No Playwright | CI/UI validation | Record absence; do not claim browser automation. |

### Performance Tests

| ID | Scenario | Load Profile | Target Metric | Threshold |
|---|---|---|---|---|
| PERF-001 | Version switch | 50 `GetVisualizerResults?version=N` requests | p99 latency | threshold TBD after representative measurement |
| PERF-002 | Save with sidecar | 95th percentile building-count GPKG | function duration and memory | below platform timeout or async-save follow-up |
| PERF-003 | Backfill | All historical edited versions in dev/test | queue duration and failures | completes without sustained queue growth |
| PERF-004 | Browser switch | Dense PMTiles + multiple sidecars | heap and interaction latency | no tab crash; both panes repaint promptly |

## Test Data Requirements

| Dataset | Description | Source | Sensitive? |
|---|---|---|---|
| Raw trained inference GeoPackage | Continuous damage fractions and `damaged` | synthetic or sanitized fixture | no |
| Raw embedding GeoPackage | Degenerate 0/1 `damage_pct_0m` copy of `damaged` | synthetic or sanitized fixture | no |
| Edited GeoPackages v1/v2 | Override `damaged` while preserving `damage_pct_0m` | synthetic | no |
| Source footprints GeoPackage | Ordered Overture ids matching prediction rows | synthetic | no |
| Raw sidecar | `prediction_attrs_${modelId}` | generated fixture | no |
| Versioned sidecars | `prediction_attrs_${modelId}_v1/v2` | generated fixture/backfill | no |
| Historical metadata | Version with `gpkgUrl` but no `predictionAttrsUrl` | synthetic plus dev models `0448`, `5553` | no |
| Large dense footprint set | Stress save/backfill/browser memory | synthetic | no |

## Coverage Matrix

| User Story | Unit | API Integration | Queue | UI | E2E | Performance |
|---|---|---|---|---|---|---|
| US-001 | — | — | — | UI-001 | E2E-001, E2E-002 | — |
| US-002 | UT-003, UT-005 | IT-009, IT-010 | — | UI-001 | E2E-001, E2E-002 | PERF-001 |
| US-003 | — | — | — | UI-005 | E2E-001, E2E-002 | PERF-004 |
| US-004 | UT-001, UT-002, UT-004, UT-007, UT-008 | IT-012, IT-013 | — | UI-009 | E2E-001, E2E-002 | PERF-002 |
| US-005 | UT-011, UT-012 | IT-001-IT-006 | — | UI-001-UI-005 | E2E-001-E2E-003 | PERF-001, PERF-004 |
| US-006 | UT-006, UT-012 | IT-015, IT-016 | — | UI-002, UI-003, UI-008 | E2E-001, E2E-005 | — |
| US-007 | — | IT-007-IT-011 | — | UI-006, UI-007 | E2E-004 | — |
| US-008 | UT-009, UT-010 | IT-014 | QT-001-QT-005 | UI-004 | E2E-003 | PERF-003 |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (Docker Compose) | Developer testing of UI, API, queue, Azurite artifacts | `docker/docker-compose.yml`; no feature flag |
| CI (GitHub Actions) | Automated backend and UI helper tests | Existing workflows plus targeted tests |
| Dev1 SWA | Backfill and selector validation with known models | Includes models `0448` and `5553` historical v1 sidecar backfill |
| Testing SWA | Pre-production analyst validation | Promote after dev sign-off |

## Sign-off Criteria

- [ ] Every selectable edited version has a matching `predictionAttrsUrl`.
- [ ] `GetVisualizerResults` version selection changes the map only.
- [ ] Assessment and Validation report buttons keep newest defaults and the UI
      warns when map/report versions can differ.
- [ ] Versioned downloads use `GetModelArtifact`, not direct blob/SAS rewriting.
- [ ] Backfill is complete for known dev historical versions or their failures
      are visible and selector options remain disabled.
- [ ] Both swipe panes update together on version switch.
- [ ] Targeted backend/API/queue tests pass.
- [ ] UI helper tests pass; Playwright/browser gap is explicitly documented if
      no Playwright config is added.
