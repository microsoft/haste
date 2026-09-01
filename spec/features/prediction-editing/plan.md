# Execution Plan: Prediction Editing

**Contents:** [Phases](#phases) · [Milestones](#milestones) · [Agent Summary](#agent-summary) · [Resource Requirements](#resource-requirements) · [Open Questions](#open-questions)

## Phases

### Phase 1: Core Library — base implemented, versioned sidecars in progress

**Goal:** Preserve append-only edited GeoPackages and add per-version sidecars so
every selectable version has renderable class data.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Keep `EditedPredictionVersion` and append-only `Model.editedPredictions`; raw `Model.gpkgUrl` remains unchanged | `backend-dev` | — | US-004 | complete (`hastelib/src/hastegeo/core/models/projects.py:343-389`, `api/hastefuncapi/function_app.py:3202-3204`) |
| Add `predictionAttrsUrl` to `EditedPredictionVersion` | `backend-dev` | versioned sidecar artifact | US-004, US-005 | complete (`hastelib/src/hastegeo/core/models/projects.py:356-389`) |
| Keep raw/model-scoped `PREDICTION_ATTRS = prediction_attrs_${modelId}` for raw predictions | `backend-dev` | — | US-002 | complete (`hastelib/src/hastegeo/core/config.py:172`) |
| Add versioned sidecar artifact type `prediction_attrs_${modelId}_v${version}` | `backend-dev` | artifact naming | US-004, US-005 | complete (`hastelib/src/hastegeo/core/config.py:178-180`) |
| Use shared `build_prediction_attrs` and `write_prediction_attrs` from `hastegeo.core.utils` | `backend-dev`, `gis` | sidecar schema | US-002, US-004, US-008 | complete (`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`, `hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:77-92`) |
| Update the prediction-tiles workflow to import the shared sidecar helpers | `gis` | shared helper move | US-002, US-008 | complete (`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:77-92`) |
| Add edited-version save helpers to build/store GeoPackage and sidecar in one call path | `backend-dev`, `gis` | shared helper, artifact naming | US-004 | complete (`hastelib/src/hastegeo/core/processors/prediction_edits.py:437-488`, `hastelib/src/hastegeo/core/processors/prediction_edits.py:520-608`) |
| Add idempotent edited-version sidecar backfill helper that skips versions with existing sidecars | `backend-dev`, `gis` | shared helper, model field | US-008 | complete (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:148-165`, `hastelib/src/hastegeo/core/processors/prediction_tiles.py:304-340`) |
| Add unit tests for versioned sidecar template rendering, save-time sidecar consistency, and backfill skip/build behavior | `backend-dev`, `gis` | implementation above | US-004, US-008 | not-started |

> **Agent column:** Use HASTE agent names (`backend-dev`, `gis`, `ui`, `security`). See [user-stories.md](user-stories.md#agent-assignment-map) for the full agent→story mapping.

**Exit Criteria:**
- [ ] Every new edited version has both `gpkgUrl` and `predictionAttrsUrl`.
- [ ] Shared sidecar helper is used by save-time generation and queue backfill.
- [ ] Backfill is idempotent and can target dev models `0448` v1 and `5553` v1.
- [ ] Raw `Model.gpkgUrl` and raw `Model.predictionAttrsUrl` semantics are unchanged.

### Phase 2: API Layer — versioned artifact contract in progress

**Goal:** Expose selected-version map payloads and downloads without adding lazy
generation to GET handlers.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Extend `GetModelArtifact` so `kind=gpkg` resolves raw with omitted/`version=0` and edited versions with `version=N` | `backend-dev` | `EditedPredictionVersion.gpkgUrl` | US-007 | in-progress (`api/hastefuncapi/function_app.py:1400-1570`) |
| Extend `GetModelArtifact` so `kind=prediction_attrs` resolves raw and versioned sidecars with the same `version` contract | `backend-dev` | versioned sidecar URLs | US-005, US-007 | in-progress (`api/hastefuncapi/function_app.py:1400-1570`) |
| Return 400 for malformed `version` and 404 for unknown positive versions in artifact and visualizer routes | `backend-dev` | version parsing | US-005, US-007 | in-progress (`api/hastefuncapi/function_app.py:157-171`, `api/hastefuncapi/function_app.py:2386-2397`) |
| Extend `GetVisualizerResults?version=N` to return the selected version's `predictionAttrsUrl` and `isNewestPredictionVersion` | `backend-dev` | visualizer payload model | US-005, US-006 | in-progress (`hastelib/src/hastegeo/core/models/visualizer.py:65-78`, `hastelib/src/hastegeo/core/processors/visualizer.py:272-329`) |
| Update `PutEditedPredictions` to call `save_edited_version`, return `predictionAttrsUrl`, and append it to `EditedPredictionVersion` | `backend-dev` | Phase 1 save helper | US-004 | in-progress (`api/hastefuncapi/function_app.py:3186-3325`) |
| Keep Assessment and Validation report buttons defaulting to newest; do not pass the View Results selector state to them | `backend-dev`, `ui` | product decision | US-006 | planned (`api/hastefuncapi/function_app.py:4607-4688`, `api/hastefuncapi/function_app.py:4929-5027`) |
| Add backfill mode to `PutPreparePredictionTilesQueueMessage` / queue worker | `backend-dev`, `gis` | Phase 1 backfill helper | US-008 | in-progress |
| Ensure backfill is not invoked from `GetVisualizerResults` or `GetModelArtifact` | `backend-dev` | API route review | US-005, US-008 | planned |
| Add API integration tests for visualizer version selection, artifact downloads, missing sidecars, unknown versions, and report default split | `backend-dev` | API changes | US-005-US-008 | not-started |

**Exit Criteria:**
- [ ] `GetVisualizerResults?version=N` selects the correct sidecar and reports whether it is newest.
- [ ] `GetModelArtifact?kind=gpkg&version=N` downloads edited versions through the Function App.
- [ ] `GetModelArtifact?kind=prediction_attrs&version=N` streams the matching sidecar.
- [ ] Unknown edited versions return 404; malformed versions return 400.
- [ ] Read paths never generate sidecars.

### Phase 3: UI — selector and downloads in progress

**Goal:** Let analysts select and download versions while clearly communicating
that reports still use newest.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add View Results version selector with Raw, newest, and saved edited versions | `ui` | `GetVisualizerResults` version payload | US-005 | in-progress |
| Refetch `GetVisualizerResults?version=N` when the selector changes | `ui` | API version contract | US-005 | in-progress (`ui/src/Components/Visualizer/Visualizer.jsx:213-223`) |
| Disable versions missing `predictionAttrsUrl` and explain that backfill has not completed | `ui` | version metadata | US-005, US-008 | planned |
| Show a map-only/report-newest warning when selected version is not newest | `ui` | `isNewestPredictionVersion` flag | US-005, US-006 | planned |
| Switch both swipe panes together by clearing/reloading sidecar and feature-state for both renderers | `ui` | PMTiles/vector state | US-003, US-005 | planned (`ui/src/Components/Visualizer/usePredictionFootprints.js:19-25`, `ui/src/Components/Visualizer/usePredictionFootprints.js:212-228`) |
| Add download button beside the selector using `GetModelArtifact?kind=gpkg&version=<selected>` | `ui` | artifact route | US-007 | in-progress |
| Add per-row download action in the edit panel version history | `ui` | artifact route | US-007 | in-progress (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`) |
| Replace direct prediction GPKG blob/SAS download usage with `GetModelArtifact` for new versioned download paths | `ui` | artifact route | US-007 | planned (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:61-69`) |
| Add helper/unit tests for selector options, disabled missing-sidecar versions, download URL generation, warning copy, and dual-pane state reset | `ui` | UI implementation | US-003, US-005, US-007, US-008 | not-started |
| Add Playwright/browser coverage | `ui-validation` | Playwright config | US-001-US-008 | not-started — repo has no Playwright config or dependency (`ui/package.json:6-15`, `ui/package.json:62-75`) |

**Exit Criteria:**
- [ ] Selecting a version changes only the map.
- [ ] Downloads are available beside the selector and per version-history row.
- [ ] Missing-sidecar versions are disabled with explanation.
- [ ] Both swipe panes switch without stale colors.
- [ ] UI helper tests pass; Playwright gap remains documented if no config is added.

### Phase 4: Integration & Deployment — TBD

**Goal:** Validate end-to-end behavior and prepare safe rollout.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Run backfill for dev models `0448` v1 and `5553` v1 | `backend-dev`, `gis` | Phases 1-2 | US-008 | not-started |
| Verify View Results selector can show raw, newest, and an older edited version | `backend-dev`, `ui`, `gis` | Phases 1-3 | US-005 | not-started |
| Verify selector changes the map only and reports still read newest | `backend-dev`, `ui`, `gis` | Phases 2-3 | US-006 | not-started |
| Verify versioned downloads from selector and edit panel rows | `backend-dev`, `ui` | Phases 2-3 | US-007 | not-started |
| Verify disabled missing-sidecar state during a simulated backfill window | `ui`, `backend-dev` | Phases 2-3 | US-005, US-008 | not-started |
| Run targeted backend/unit tests for sidecar, save, backfill, and artifact resolution | `backend-validation` | Phases 1-2 | US-004, US-005, US-007, US-008 | not-started |
| Run targeted UI helper tests and record Playwright absence | `ui-validation` | Phase 3 | US-003, US-005, US-007 | not-started |

**Exit Criteria:**
- [ ] Dev backfill completes or failures are visible and actionable.
- [ ] Versioned sidecar and GeoPackage URLs match for every selectable version.
- [ ] Map/report mismatch warning is visible when applicable.
- [ ] Direct blob/SAS URL download paths are not used for new version downloads.
- [ ] Known follow-ups are triaged: concurrent-save 409, Playwright/browser validation, Assessment semantics, and producer-side Overture ids.

## Milestones

| Milestone | Date | Deliverable |
|---|---|---|
| Spec amended | 2026-08-25 | Draft spec and ADR describe per-version sidecars, map-only selection, downloads, and backfill. |
| Core/API contract done | TBD | Versioned sidecar schema, helpers, save path, artifact resolution, and backfill implemented. |
| UI selector/downloads done | TBD | View Results selector, warnings, disabled states, and downloads working. |
| Dev validation done | TBD | Backfill and E2E selector/download scenarios verified in dev. |
| Release | TBD | Feature promoted after dev/test validation. |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | data model, API, artifact resolution, save, backfill | 1, 2, 4 |
| `gis` | sidecar correctness, GeoPackage row order, backfill validation | 1, 2, 4 |
| `ui` | selector, warning, dual-pane switch, downloads | 3, 4 |
| `backend-validation` | targeted backend and queue validation | 4 |
| `ui-validation` | UI helper validation and Playwright-gap reporting | 3, 4 |
| `security` | 0 | —; no new dependency is expected |

## Resource Requirements

- **Agents:** `backend-dev`, `gis`, `ui`, `backend-validation`, and
  `ui-validation`.
- **Azure services:** Existing Cosmos metadata store, Blob Storage, Queue
  Storage, Azure Functions, and existing Batch/runner capacity.
- **GPU compute:** None required for editing, sidecar generation, or backfill.
- **External data:** None beyond existing project imagery, footprints, raw
  predictions, and edited GeoPackages.

## Open Questions

- [ ] Decide whether high-volume saves need an async save path after measuring
      production layer sizes.
- [ ] Add optimistic concurrency for simultaneous saves before supporting
      multi-analyst editing of the same model.
- [ ] Decide how Assessment counts should incorporate per-building overrides
      when edited GeoPackages preserve the producer's original `damage_pct_0m`.
- [ ] Fix or explicitly mitigate pre-existing positional-join risks in raw
      prediction producers.
