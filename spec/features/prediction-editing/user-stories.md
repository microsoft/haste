# User Stories: Prediction Editing

**Contents:** [Personas](#personas) · [Stories](#stories) · [Agent Assignment Map](#agent-assignment-map) · [Story Map](#story-map) · [Out of Scope](#out-of-scope)

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Domain expert who reviews building-level damage predictions during response | Correct model outputs quickly, compare versions, and preserve provenance |
| ML Engineer | Builds and evaluates trained and embedding-based prediction workflows | Keep raw model outputs immutable while making versioned artifacts testable |
| External Partner | Collaborator who receives HASTE-generated files | Download a clear raw or edited deliverable without editor access |

---

## Stories

### US-001: Open Results and Enter Edit Mode from Any Completed Prediction Workflow

**As a** Disaster Analyst,
**I want to** open View Results from both trained-inference and embedding model rows and enter edit mode there,
**So that** I can review and correct predictions without leaving the results map.

**Priority:** P0
**Estimate:** M
**Component(s):** `ui/src/Components/ProjectManagement/`, `ui/src/Components/Visualizer/`

**Acceptance Criteria:**

```gherkin
Given a model with server-derived predictionsReady true
When I open the Results menu
Then View navigates to /visualizer/:projectId/:imageLayerId/:modelId
And there is no standalone /edit-predictions route
```

```gherkin
Given the View Results page has loaded predicted footprints and attributes
When I click the pencil next to Back or press E
Then the same /visualizer page enters prediction edit mode
```

**Notes:** The existing route and edit affordance live in `AppBody.jsx` and
`Labels.jsx` (`ui/src/Components/AppBody.jsx:73-75`,
`ui/src/Components/Visualizer/Labels.jsx:117-128`).

---

### US-002: Prepare a Complete Footprint Results/Edit Session

**As a** Disaster Analyst,
**I want to** load all predicted building footprints and raw prediction attributes,
**So that** both viewing and editing cover the complete model output.

**Priority:** P0
**Estimate:** L
**Component(s):** `api/hastefuncapi`, `api/hastefuncqueues`, `hastelib`, `ui/src/Components/Visualizer/`

**Acceptance Criteria:**

```gherkin
Given GetVisualizerResults returns footprintTilesUrl and predictionAttrsUrl
When the UI loads the results page
Then it fetches PMTiles and prediction attributes through GetModelArtifact
And it renders predicted buildings as vectors for either workflow
```

```gherkin
Given PMTiles or raw attributes are missing
When preparation is requested
Then the queued prediction-tiles job generates missing artifacts
And GET handlers do not run tippecanoe inline
```

**Notes:** `GetModelArtifact` streams artifacts server-side
(`api/hastefuncapi/function_app.py:1430-1570`). The sidecar builder now lives in shared core utilities and the workflow imports
it (`hastelib/src/hastegeo/core/utils/prediction_attrs.py:128-202`,
`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:77-92`).

---

### US-003: Reclassify Buildings and Re-threshold Trained Predictions

**As a** Disaster Analyst,
**I want to** reclassify individual or selected groups of buildings and adjust a threshold where valid,
**So that** I can produce a corrected damage layer that reflects expert review.

**Priority:** P0
**Estimate:** L
**Component(s):** `ui/src/Components/Visualizer/PredictionEditPanel.jsx`, `ui/src/Components/Visualizer/usePredictionFootprints.js`

**Acceptance Criteria:**

```gherkin
Given edit mode loaded a trained-inference model
When I move the damage or unknown threshold slider
Then footprint colors update live from the sidecar
```

```gherkin
Given edit mode loaded an embedding model
When I view the edit panel
Then threshold sliders are hidden
And I can still set Damaged, NotDamaged, or Unknown overrides
```

```gherkin
Given the swipe map is visible
When I edit footprints or switch versions
Then both swipe panes show the same classes and selection state
```

**Notes:** Feature-state writes must be mirrored to both panes; otherwise one
pane can remain on stale colors (`ui/src/Components/Visualizer/usePredictionFootprints.js:19-25`,
`ui/src/Components/Visualizer/usePredictionFootprints.js:212-228`).

---

### US-004: Save an Edited Prediction GeoPackage as a New Version

**As a** Disaster Analyst,
**I want to** save corrections as `edit_v1`, `edit_v2`, and later numbered versions,
**So that** the original model output remains auditable and recoverable.

**Priority:** P0
**Estimate:** L
**Component(s):** `api/hastefuncapi`, `hastelib/src/hastegeo/core/models/`, `hastelib/src/hastegeo/core/processors/`, Blob Storage, `ui/src/Components/Visualizer/`

**Acceptance Criteria:**

```gherkin
Given a loaded prediction edit mode session and a set of overrides
When I save a new version
Then PutEditedPredictions writes a new GeoPackage and a matching prediction_attrs sidecar
And the Model document appends one EditedPredictionVersion entry with gpkgUrl and predictionAttrsUrl
And Model.gpkgUrl remains the raw prediction pointer
```

```gherkin
Given sidecar generation fails after the GeoPackage is written
When the save response is returned
Then the version is not advertised as selectable
And the failure is visible to the analyst
```

**Notes:** The current API route appends metadata after storing a versioned GPKG
(`api/hastefuncapi/function_app.py:3302-3325`). It must adopt the shared helper
that writes the sidecar in the same call path before metadata append
(`hastelib/src/hastegeo/core/processors/prediction_edits.py:520-608`). The current implementation still
has no optimistic concurrency or 409 response.

---

### US-005: Select Which Prediction Version the Map Shows

**As a** Disaster Analyst,
**I want to** choose raw, newest, or a saved edited version on View Results,
**So that** I can compare map output across review passes.

**Priority:** P0
**Estimate:** M
**Component(s):** `api/hastefuncapi`, `hastelib/src/hastegeo/core/processors/visualizer.py`, `ui/src/Components/Visualizer/`

**Acceptance Criteria:**

```gherkin
Given a model has raw predictions and edited versions 1, 2, and 3
When I select version 2 on View Results
Then the UI calls GetVisualizerResults?version=2
And the map renders the sidecar for version 2
And the response says isNewestPredictionVersion is false
```

```gherkin
Given the map is showing raw or an older version while a newer edit exists
When report actions are visible
Then the UI states that Assessment and Validation reports still use the newest version
```

```gherkin
Given a version has no predictionAttrsUrl because backfill has not completed
When I open the selector
Then that version is disabled and explains that its sidecar is still being prepared
```

**Notes:** The current visualizer fetch omits `version` and must be extended
(`ui/src/Components/Visualizer/Visualizer.jsx:213-223`). This story changes the
map only; it does not add an active-version pointer.

---

### US-006: Keep Reports on the Newest Version Unless Explicitly Requested

**As an** ML Engineer,
**I want to** keep Assessment and Validation report defaults stable while map selection changes,
**So that** report URLs remain predictable and newest-edited analysis stays the default.

**Priority:** P0
**Estimate:** M
**Component(s):** `api/hastefuncapi`, `hastelib/src/hastegeo/core/utils/predictions.py`, `ui/src/Components/Visualizer/`

**Acceptance Criteria:**

```gherkin
Given the View Results map is showing version 2 and version 3 also exists
When I request Validation or Assessment from the standard UI buttons
Then the request omits version
And the backend resolves version 3
```

```gherkin
Given an API caller explicitly passes version=0 or version=N to a report endpoint
When the version exists
Then the endpoint keeps honoring that explicit contract
And an unknown numeric version returns 404
```

```gherkin
Given an edited GeoPackage changes damaged but preserves damage_pct_0m
When reports run
Then Validation metrics can move with damaged
But Assessment threshold counts remain tied to damage_pct_0m until a follow-up changes that product decision
```

**Notes:** The report routes already parse optional versions and resolve the
selected source (`api/hastefuncapi/function_app.py:4607-4688`,
`api/hastefuncapi/function_app.py:4929-5027`). The UI selector must not mutate
those report defaults.

---

### US-007: Download Raw or Edited Prediction Versions

**As an** External Partner,
**I want to** download the selected map version or a specific saved row,
**So that** I receive the exact GeoPackage I need without direct blob access.

**Priority:** P0
**Estimate:** M
**Component(s):** `api/hastefuncapi/function_app.py`, `ui/src/Components/Visualizer/PredictionEditPanel.jsx`, `ui/src/Components/ProjectManagement/ModelResultsButton.jsx`

**Acceptance Criteria:**

```gherkin
Given View Results is showing raw or edited version N
When I click Download beside the version selector
Then the browser downloads GetModelArtifact?kind=gpkg&version=<selected>
And the request goes through the Function App auth path
```

```gherkin
Given the edit panel shows saved versions
When I click a row's download action
Then HASTE downloads that row's GeoPackage through GetModelArtifact with the row version
```

```gherkin
Given an unknown version is requested for download
When GetModelArtifact resolves it
Then it returns 404 rather than a direct blob URL fallback
```

**Notes:** Current model-row download code rewrites direct blob/SAS URLs
(`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:61-69`,
`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:113-119`). New
version downloads use `GetModelArtifact`, which already handles Range and
content disposition (`api/hastefuncapi/function_app.py:1430-1570`).

---

### US-008: Backfill Sidecars for Existing Edited Versions

**As an** ML Engineer,
**I want to** generate missing sidecars for versions saved before this change,
**So that** historical edits can become selectable without adding generation to the read path.

**Priority:** P0
**Estimate:** M
**Component(s):** `hastelib/src/hastegeo/core/processors/prediction_tiles.py`, `api/hastefuncqueues/function_app.py`, Blob Storage, Cosmos DB

**Acceptance Criteria:**

```gherkin
Given an edited version has gpkgUrl but no predictionAttrsUrl
When the prediction-tiles job runs in backfill mode
Then it builds prediction_attrs_${modelId}_v${version}
And updates that EditedPredictionVersion with predictionAttrsUrl
```

```gherkin
Given a version already has predictionAttrsUrl and force is false
When backfill runs
Then the job skips that version without rewriting it
```

```gherkin
Given dev models 0448 and 5553 each have version 1 without sidecars
When the backfill is run
Then both versions receive sidecars or a visible failure status
```

**Notes:** Backfill is not lazy on first selection. The selector must disable
versions until the sidecar URL is present.

---

## Agent Assignment Map

Every user story must be assigned to one or more HASTE agents. The **implementing agent** writes the code; the **validating agent** verifies correctness against acceptance criteria. See [Agent Architecture](../../architecture/overview.md#agent-architecture) for full agent descriptions.

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend, API, processors, data layers, runners | Yes |
| `gis` | Satellite imagery, GDAL/rasterio, vector tiles, GeoPackage handling, damage assessment | Yes |
| `ui` | React/FluentUI/Azure Maps/MSAL, frontend only | Yes |
| `backend-validation` | Validates backend code against specs, conventions, tests | No (validates only) |
| `ui-validation` | Validates frontend changes against expected behavior | No (validates only) |

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` | UI entry point uses server-derived readiness. |
| US-002 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` | Prep/API ownership is backend; row-order and GeoPackage logic require GIS review. |
| US-003 | `ui` | `ui-validation` | UI edit-mode behavior and dual-pane feature state. |
| US-004 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` | Save writes GPKG + sidecar; UI resets baseline. |
| US-005 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` | Map-only version selection and warning copy. |
| US-006 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` | Reports keep newest; UI must not pass selector version. |
| US-007 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` | Downloads route through `GetModelArtifact`. |
| US-008 | `backend-dev`, `gis` | `backend-validation` | Idempotent backfill for historical versions. |

### Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Phase 1 — Data Model & Artifact Contract | `backend-dev` | `gis` | `backend-validation` |
| Phase 2 — Prep Workflow, Readiness & API | `backend-dev` | `gis` | `backend-validation` |
| Phase 3 — Results Viewer Edit Mode | `ui` | `backend-dev`, `gis` | `ui-validation`, `backend-validation` |
| Phase 4 — Integration | `backend-dev` | `ui`, `gis` | `backend-validation`, `ui-validation` |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-001 | Phase 2/3 — Readiness & UI Entry | `backend-dev`, `ui` | model payloads, Visualizer route |
| P0 | US-002 | Phase 2/3 — Prep Workflow & Vector Viewer | `backend-dev`, `gis`, `ui` | `hastelib`, queues, Visualizer artifacts |
| P0 | US-003 | Phase 3 — Results Viewer Edit Mode | `ui` | Visualizer edit panel and map state |
| P0 | US-004 | Phase 1/2/3 — Data Model, API & UI Save | `backend-dev`, `gis`, `ui` | GPKG + sidecar save |
| P0 | US-005 | Phase 2/3 — Map Version Selection | `backend-dev`, `ui` | `GetVisualizerResults`, selector |
| P0 | US-006 | Phase 2/3 — Report Default Split | `backend-dev`, `gis`, `ui` | report endpoints and UI warning |
| P0 | US-007 | Phase 2/3 — Version Downloads | `backend-dev`, `ui` | `GetModelArtifact`, download controls |
| P0 | US-008 | Phase 2/4 — Backfill | `backend-dev`, `gis` | prediction-tiles job and metadata |

## Out of Scope

Stories explicitly excluded from this feature:

- [ ] Publish edited versions through the data-publishing workflow.
- [ ] Add collaborative real-time editing, locking, 409 conflict handling, or audit diff playback.
- [ ] Resolve the Assessment-report asymmetry where edited `damaged` changes Validation metrics but preserved `damage_pct_0m` drives threshold-based Assessment counts.
- [ ] Add browser/Playwright coverage in this branch; the repo has no Playwright config.
- [ ] Fix the pre-existing positional-join risks in the classic prediction writer or add explicit producer-side `overture_id` columns.
