# User Stories: Prediction Editing

**Contents:** [Personas](#personas) · [Stories](#stories) · [Agent Assignment Map](#agent-assignment-map) · [Story Map](#story-map) · [Out of Scope](#out-of-scope)

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Domain expert who reviews building-level damage predictions during response | Correct model outputs quickly and preserve provenance |
| ML Engineer | Builds and evaluates trained and embedding-based prediction workflows | Keep raw model outputs immutable while comparing edited versions |
| External Partner | Collaborator who receives HASTE-generated files | Download a clear edited deliverable without needing editor access |

---

## Stories

### US-001: Open Results and Enter Edit Mode from Any Completed Prediction Workflow

**As a** Disaster Analyst,
**I want to** open View Results from both trained-inference and embedding model rows and enter edit mode there,
**So that** I can review and correct predictions without leaving the results map.

**Priority:** P0
**Estimate:** M
**Component(s):** `ui/src/Components/ProjectManagement/ModelResultsButton.jsx`, `ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx`, `ui/src/Components/AppBody.jsx`, `ui/src/Components/Visualizer/Labels.jsx`, `ui/src/Components/Visualizer/Visualizer.jsx`

**Acceptance Criteria:**

```gherkin
Given a trained-inference model with server-derived predictionsReady true
When I open the Results menu
Then the View item is enabled and navigates to /visualizer/:projectId/:imageLayerId/:modelId
And there is no standalone Edit button on the model row
```

```gherkin
Given an embedding model with server-derived predictionsReady true
When I open the embedding Results menu
Then View is the first menu item and navigates to /visualizer/:projectId/:imageLayerId/:modelId
And there is no standalone Edit button on the embedding row
```

```gherkin
Given the View Results page has loaded predicted footprints and attributes
When I click the pencil next to Back or press E
Then the same /visualizer page enters prediction edit mode
And the edit panel replaces the read-only overlay controls
```

```gherkin
Given I am in edit mode with unsaved edits
When I click Done or press E
Then HASTE asks me to discard unsaved edits before leaving edit mode
```

```gherkin
Given the model is not ready, has no predictions, has no predicted buildings, or is still preparing vector artifacts
When I view the Results menu or the visualizer edit affordance
Then the disabled state explains why editing cannot open yet
```

**UI Wireframe:** The Results menu opens the existing View Results route. A
pencil/Done button sits beside Back on the visualizer; edit mode overlays a
right-side edit panel on the same swipe map.

**Notes:** `AppBody.jsx` registers `/visualizer/...` and no
`/edit-predictions/...` route (`ui/src/Components/AppBody.jsx:73-75`). The
trained row and embedding row both navigate to `/visualizer/...` from View
(`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:87-110`,
`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:116-130`). The
pencil affordance and `E` shortcut are wired in `Labels.jsx` and `Visualizer.jsx`
(`ui/src/Components/Visualizer/Labels.jsx:117-128`,
`ui/src/Components/Visualizer/Visualizer.jsx:496-605`).

---

### US-002: Prepare a Complete Footprint Results/Edit Session

**As a** Disaster Analyst,
**I want to** load all predicted building footprints, not a sample,
**So that** both viewing and editing cover the complete model output.

**Priority:** P0
**Estimate:** L
**Component(s):** `api/hastefuncapi`, `api/hastefuncqueues`, `hastelib`, `docker/training`, `ui/src/Components/Visualizer/`

**Acceptance Criteria:**

```gherkin
Given GetVisualizerResults returns footprintTilesUrl and predictionAttrsUrl
When the UI loads the results page
Then it fetches the PMTiles archive and prediction attribute sidecar through GetModelArtifact routes
And it renders predicted buildings as vectors for either workflow
```

```gherkin
Given the model has predictions but PMTiles or attributes are missing
When GetVisualizerResults reports predictionsReadiness.reason "preparing" or the artifact request returns 404
Then the UI calls GetPredictionEditSession and PutPreparePredictionTilesQueueMessage
And it polls GetPredictionEditSession until tilesReady and attrsReady are true
```

```gherkin
Given GetPredictionEditSession is called for a raw prediction GeoPackage
When the raw GeoPackage can be read
Then the response includes tilesReady, attrsReady, buildingCount, flavor, supportsThreshold, defaultThreshold, predictionTilesStatus, predictionTilesStatusMessage, and versions
And the GET does not enqueue work or run tippecanoe inline
```

```gherkin
Given source footprints and predictions have different row counts
When the prep worker validates the session inputs
Then it fails the prep job and records a user-visible readiness error
```

**UI Wireframe:** Results page status note with spinner/retry while predicted
buildings are prepared; once ready, the same vector footprint layer is visible
in read-only and edit modes.

**Notes:** `GetModelArtifact` streams `footprint_pmtiles` and `prediction_attrs`
through the API (`api/hastefuncapi/function_app.py:1400-1424`,
`api/hastefuncapi/function_app.py:1453-1458`). The visualizer artifact hook owns
loading, queueing, and polling (`ui/src/Components/Visualizer/usePredictionArtifacts.js:4-24`,
`ui/src/Components/Visualizer/usePredictionArtifacts.js:224-299`,
`ui/src/Components/Visualizer/usePredictionArtifacts.js:377-459`). The prep job
runs in the queue/training-image path because `tippecanoe` is not an HTTP-handler
concern (`hastelib/src/hastegeo/core/processors/prediction_tiles.py:13-19`,
`api/hastefuncqueues/function_app.py:861-914`,
`hastelib/src/hastegeo/workflows/prepare_prediction_tiles.py:40-45`).

---

### US-003: Reclassify Buildings and Re-threshold Trained Predictions

**As a** Disaster Analyst,
**I want to** reclassify individual or selected groups of buildings and adjust a threshold where valid,
**So that** I can produce a corrected damage layer that reflects expert review.

**Priority:** P0
**Estimate:** L
**Component(s):** `ui/src/Components/Visualizer/PredictionEditPanel.jsx`, `ui/src/Components/Visualizer/usePredictionFootprints.js`, `ui/src/Components/Visualizer/predictionClassify.js`, `ui/src/Components/Visualizer/predictionFootprintMap.js`

**Acceptance Criteria:**

```gherkin
Given edit mode loaded a trained-inference model
When I move the damage or unknown threshold slider
Then footprint colors update live from the sidecar and the panel shows how many buildings would change class
```

```gherkin
Given edit mode loaded an embedding model
When I view the edit panel
Then no threshold slider is shown
And I can still set explicit Damaged, NotDamaged, or Unknown overrides
```

```gherkin
Given visible predicted footprints on the map
When I click a building or ctrl+drag a selection box
Then selected buildings can be assigned Damaged, NotDamaged, or Unknown
And the edited count updates
```

```gherkin
Given the swipe map is visible
When I edit footprints on either side of the divider
Then feature-state coloring and selection stay mirrored between the two panes
```

**UI Wireframe:** Azure Maps swipe canvas underneath a right panel with class
counts, filters, prev/next traversal, threshold controls when supported, saved
version history, Save as new version, and Done editing.

**Notes:** The edit panel lives in the Visualizer directory and is rendered only
when `isEditMode` is true (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:4-16`,
`ui/src/Components/Visualizer/Visualizer.jsx:873-921`). Map classification is
browser-side feature-state over PMTiles, so threshold moves do not need a server
round trip (`ui/src/Components/Visualizer/usePredictionFootprints.js:4-29`,
`ui/src/Components/Visualizer/predictionFootprintMap.js:4-18`).

---

### US-004: Save an Edited Prediction GeoPackage as a New Version

**As a** Disaster Analyst,
**I want to** save corrections as `edit_v1`, `edit_v2`, and later numbered versions,
**So that** the original model output remains auditable and recoverable.

**Priority:** P0
**Estimate:** L
**Component(s):** `api/hastefuncapi`, `hastelib/src/hastegeo/core/models/`, `hastelib/src/hastegeo/core/processors/`, Blob Storage, `ui/src/Components/Visualizer/usePredictionFootprints.js`

**Acceptance Criteria:**

```gherkin
Given a loaded prediction edit mode session and a set of overrides
When I save with threshold 0.1 and unknownThreshold 0.0
Then PutEditedPredictions returns version, gpkgUrl, and editedCount
And the Model document appends one EditedPredictionVersion entry
And Model.gpkgUrl remains the raw prediction pointer
```

```gherkin
Given a source prediction GeoPackage with N rows
When an edited GeoPackage is written
Then the edited file has N rows in the exact same order, preserves the source geometry, writes overture_id, edited_class, and edit_threshold, and sets damaged to 1 only for final_class Damaged
```

```gherkin
Given a save has succeeded
When the edit panel refreshes versions
Then the saved version appears in the history and the saved baseline becomes the new unsaved-edits baseline
```

**UI Wireframe:** Save button displays success/failure in the edit panel. The
saved version appears in the right-panel history; the rows are informational in
this branch.

**Notes:** The save path builds the sparse `PutEditedPredictions` payload in the
visualizer hook (`ui/src/Components/Visualizer/usePredictionFootprints.js:838-887`).
The API appends metadata without touching `gpkgUrl` (`api/hastefuncapi/function_app.py:3181-3345`).
The current implementation does not implement optimistic concurrency or a 409
conflict response; concurrent saves can collide and need a follow-up fix.

---

### US-005: Show Edited Version History Without Switching Versions in the UI

**As an** External Partner,
**I want to** identify saved edited prediction versions,
**So that** I can request or download the correct analyst-reviewed file while HASTE keeps raw outputs separate.

**Priority:** P1
**Estimate:** M
**Component(s):** `api/hastefuncapi`, `ui/src/Components/Visualizer/PredictionEditPanel.jsx`, `hastelib/src/hastegeo/core/models/`

**Acceptance Criteria:**

```gherkin
Given a model with editedPredictions entries
When GetVisualizerResults or GetPredictionEditSession returns
Then the payload includes predictionVersions or versions sorted newest first
And the edit panel displays version, timestamp, threshold, editor, and edited count
```

```gherkin
Given I view the Saved versions list in edit mode
When I click or focus a version row
Then the row does not refetch the map or switch the served version in the current branch
And the active version badge only reports the version already on the map
```

```gherkin
Given I need a specific edited GeoPackage
When I call GetEditedPredictionVersions or inspect the visualizer payload
Then the gpkgUrl for each edited version is available while raw Model.gpkgUrl is unchanged
```

**UI Wireframe:** Version history list in the edit panel. The active version gets
an "On the map" badge; rows are read-only until a follow-up wires selection to a
`GetVisualizerResults?version=N` refetch.

**Notes:** `PredictionEditPanel` renders history without an `onClick`/selection
handler (`ui/src/Components/Visualizer/PredictionEditPanel.jsx:513-550`). The
visualizer fetch currently omits `version`, so UI version switching is not wired
(`ui/src/Components/Visualizer/Visualizer.jsx:213-223`).

---

### US-006: Read Edited Versions in Results and Reports

**As an** ML Engineer,
**I want to** use the same raw-or-edited prediction source selection in every reader,
**So that** visual results and validation/report metrics reflect saved analyst edits consistently where their data model allows it.

**Priority:** P0
**Estimate:** M
**Component(s):** `api/hastefuncapi`, `hastelib/src/hastegeo/core/utils/predictions.py`, `hastelib/src/hastegeo/core/processors/visualizer.py`, `docs/api/hastefuncapi.md`

**Acceptance Criteria:**

```gherkin
Given a model has editedPredictions versions 1 and 2
When GetVisualizerResults, GetValidationReport, or GetAssessmentReport is called without version
Then the reader uses version 2
```

```gherkin
Given a model has editedPredictions versions 1 and 2
When a reader is called with version=0
Then the reader uses raw Model.gpkgUrl
```

```gherkin
Given a model has editedPredictions versions 1 and 2
When a reader is called with version=1
Then the reader uses version 1
And an unknown numeric version returns 404 while a malformed version returns 400
```

```gherkin
Given an edited GeoPackage changes damaged but preserves damage_pct_0m
When GetValidationReport computes metrics
Then the explicit edits affect validation because it reads damaged
But GetAssessmentReport threshold-based counts continue to derive from damage_pct_0m until a follow-up resolves that product decision
```

**UI Wireframe:** The results map displays the served version in the edit panel;
UI controls for switching versions remain a follow-up.

**Notes:** `resolve_prediction_source` implements newest-wins, explicit version,
and `version=0` raw selection (`hastelib/src/hastegeo/core/utils/predictions.py:332-401`).
The three readers call it (`api/hastefuncapi/function_app.py:2386-2435`,
`api/hastefuncapi/function_app.py:4677-4688`,
`api/hastefuncapi/function_app.py:5017-5027`). The API docs capture the full
reader contract and the validation/assessment asymmetry (`docs/api/hastefuncapi.md:480-502`).

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
| US-001 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` | UI entry point uses server-derived `predictionsReady`; no standalone route. |
| US-002 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` | Queue/API ownership is backend; PMTiles, GeoPackage, CRS, and row-order checks require GIS review; visualizer owns artifact loading. |
| US-003 | `ui` | `ui-validation` | UI edit-mode behavior; GIS should be consulted for class semantics but does not own UI code. |
| US-004 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` | Version metadata plus GeoPackage read/write and row-order invariant; UI save wiring. |
| US-005 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` | API version list and read-only UI history; version switching remains a follow-up. |
| US-006 | `backend-dev`, `gis` | `backend-validation` | Raw-vs-edited source resolution across visualizer, validation, and assessment; assessment semantics need GIS/product follow-up. |

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
| P0 | US-001 | Phase 2/3 — Readiness & UI Entry | `backend-dev`, `ui` | model payloads, `ui/src/Components/ProjectManagement/`, `ui/src/Components/Visualizer/` |
| P0 | US-002 | Phase 2/3 — Prep Workflow & Vector Viewer | `backend-dev`, `gis`, `ui` | `hastelib`, `hastefuncapi`, `hastefuncqueues`, `ui/src/Components/Visualizer/` |
| P0 | US-003 | Phase 3 — Results Viewer Edit Mode | `ui` | `ui/src/Components/Visualizer/` |
| P0 | US-004 | Phase 1/2/3 — Data Model, API & UI Save | `backend-dev`, `gis`, `ui` | `hastelib`, Blob Storage, `hastefuncapi`, Visualizer hooks |
| P1 | US-005 | Phase 3/4 — Version History | `backend-dev`, `ui` | `hastefuncapi`, `ui/src/Components/Visualizer/` |
| P0 | US-006 | Phase 2/4 — Reader Integration | `backend-dev`, `gis` | `hastefuncapi`, `hastelib/src/hastegeo/core/utils/predictions.py` |

## Out of Scope

Stories explicitly excluded from this feature:

- [ ] Publish edited versions through the data-publishing workflow.
- [ ] Switch served prediction versions from the UI; history is read-only in the current branch.
- [ ] Add a dedicated one-click edited-version download button in the edit panel.
- [ ] Add collaborative real-time editing, locking, 409 conflict handling, or audit diff playback.
- [ ] Introduce a generic artifact registry beyond the Model-level edited version list.
- [ ] Resolve the assessment-report asymmetry where edited `damaged` changes validation metrics but preserved `damage_pct_0m` drives threshold-based assessment counts.
- [ ] Fix the pre-existing positional-join risks in the classic prediction writer or add explicit producer-side `overture_id` columns.
