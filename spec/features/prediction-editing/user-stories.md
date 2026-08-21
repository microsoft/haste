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

### US-001: Open the Prediction Editor from Any Completed Prediction Workflow

**As a** Disaster Analyst,
**I want to** open an Edit screen from both trained-inference and embedding model rows,
**So that** I can correct predictions without caring which workflow produced them.

**Priority:** P0
**Estimate:** M
**Component(s):** `ui/src/Components/ProjectManagement/ModelResultsButton.jsx`, `ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx`, `ui/src/Components/AppBody.jsx`

**Acceptance Criteria:**

```gherkin
Given a trained-inference model with inferenceStatus "Processed" and a non-empty gpkgUrl
When I view the model row
Then the Edit button is enabled and navigates to /edit-predictions/:projectId/:imageLayerId/:modelId
```

```gherkin
Given an embedding model with a non-empty gpkgUrl and predictedBuildingCount greater than 0
When I view the embedding model row
Then the Edit button is enabled and navigates to /edit-predictions/:projectId/:imageLayerId/:modelId
```

```gherkin
Given a trained model without processed inference or without gpkgUrl
When I view the model row
Then the Edit button is disabled
```

```gherkin
Given an embedding model whose gpkgUrl was set by an empty prediction write
When predictedBuildingCount is 0 or missing
Then the Edit button is disabled
```

**UI Wireframe:** The Edit button appears beside existing result actions on each
model row and opens a full-screen editor route.

**Notes:** Current trained gating uses `inferenceStatus === "Processed"`; current
embedding gating only checks `!!model.gpkgUrl`, which is ambiguous
(`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:43-46`,
`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx:86`).

---

### US-002: Prepare a Complete Footprint Editing Session

**As a** Disaster Analyst,
**I want to** load all predicted building footprints, not a sample,
**So that** edits cover the complete model output.

**Priority:** P0
**Estimate:** L
**Component(s):** `api/hastefuncapi`, `api/hastefuncqueues`, `hastelib`, `docker/training`

**Acceptance Criteria:**

```gherkin
Given a model with a raw prediction GeoPackage and existing footprint PMTiles and prediction attributes
When the UI calls GetPredictionEditSession
Then the response includes tilesReady true, attrsReady true, buildingCount, flavor, supportsThreshold, defaultThreshold, predictionTilesStatus, predictionTilesStatusMessage, and versions
```

```gherkin
Given the raw prediction GeoPackage exists but PMTiles or attributes are missing
When the UI calls GetPredictionEditSession
Then the response is side-effect-free and returns tilesReady false or attrsReady false without enqueueing work or running tippecanoe inline
```

```gherkin
Given the raw prediction GeoPackage exists but PMTiles or attributes are missing
When the UI calls PutPreparePredictionTilesQueueMessage with projectId, imageLayerId, modelId, and optional force
Then the API returns modelId, queued, tilesReady, attrsReady, status, and statusMessage, and enqueues exactly one prediction-edit-prep message unless artifacts are already ready or a job is already Queued/InProgress
```

```gherkin
Given source footprints and predictions have different row counts
When the prep worker validates the session inputs
Then it fails the prep job and records a user-visible readiness error
```

**UI Wireframe:** Preparation state with spinner, retry, and a short explanation
that full editor tiles are being generated.

**Notes:** `GetBuildingFootprintsGeoJSON` is a random sample capped at 2,000
features and must not be used for editing (`api/hastefuncapi/function_app.py:3626`,
`api/hastefuncapi/function_app.py:3645-3663`). `tippecanoe` is available only in
the training image (`docker/training/env/env.yml:11`).

---

### US-003: Reclassify Buildings and Re-threshold Trained Predictions

**As a** Disaster Analyst,
**I want to** reclassify individual or selected groups of buildings and adjust a threshold where valid,
**So that** I can produce a corrected damage layer that reflects expert review.

**Priority:** P0
**Estimate:** L
**Component(s):** `ui/src/Components/PredictionEditor/`, `ui/src/Components/InteractiveLabeler/InteractiveLabeler.jsx`, `ui/src/Components/BuildingValidation/BuildingValidation.jsx`

**Acceptance Criteria:**

```gherkin
Given the editor loaded a trained-inference model
When I move the threshold slider
Then footprint colors update live from the sidecar and the panel shows how many buildings would flip
```

```gherkin
Given the editor loaded an embedding model
When I view the right panel
Then no threshold slider is shown and I can still set explicit Damaged, NotDamaged, or Unknown overrides
```

```gherkin
Given visible footprints on the map
When I click a building or ctrl+drag a selection box
Then selected buildings can be assigned Damaged, NotDamaged, or Unknown and the edited count updates
```

**UI Wireframe:** Azure Maps canvas on the left, right panel with class filters,
counts, prev/next traversal, threshold controls when supported, version history,
and Save as new version.

**Notes:** Use PMTiles in-memory loading, feature-state coloring, and box-select
patterns from `InteractiveLabeler.jsx`; use filter/traversal patterns from
`BuildingValidation.jsx`. Use Fluent `makeStyles` and `tokens` for dark mode.

---

### US-004: Save an Edited Prediction GeoPackage as a New Version

**As a** Disaster Analyst,
**I want to** save corrections as `edit_v1`, `edit_v2`, and later numbered versions,
**So that** the original model output remains auditable and recoverable.

**Priority:** P0
**Estimate:** L
**Component(s):** `api/hastefuncapi`, `hastelib/src/hastegeo/core/models/`, `hastelib/src/hastegeo/core/processors/`, Blob Storage

**Acceptance Criteria:**

```gherkin
Given a loaded prediction edit session and a set of overrides
When I save with threshold 0.1 and unknownThreshold 0.0
Then PutEditedPredictions returns version, gpkgUrl, and editedCount and the Model document appends one EditedPredictionVersion entry
```

```gherkin
Given a source prediction GeoPackage with N rows
When an edited GeoPackage is written
Then the edited file has N rows in the exact same order, preserves the source geometry, writes overture_id, edited_class, and edit_threshold, and sets damaged to 1 only for final_class Damaged
```

**UI Wireframe:** Save button opens a confirmation state, then displays the new
version in the right panel history.

**Notes:** Existing storage overwrites same-named artifacts, so the versioned
artifact name is the immutability boundary
(`hastelib/src/hastegeo/core/artifact_storage/azure_blob_artifact_storage.py:255`).
The current implementation does not implement optimistic concurrency or a 409
conflict response; concurrent saves can collide and need a follow-up fix.

---

### US-005: List and Download Edited Versions

**As an** External Partner,
**I want to** download a named edited prediction version,
**So that** I can consume the analyst-reviewed file while HASTE keeps raw outputs separate.

**Priority:** P1
**Estimate:** M
**Component(s):** `api/hastefuncapi`, `ui/src/Components/PredictionEditor/`, `hastelib/src/hastegeo/core/models/`

**Acceptance Criteria:**

```gherkin
Given a model with editedPredictions entries
When the UI calls GetEditedPredictionVersions
Then it receives the versions sorted by version number or creation time and can display the threshold, editor, edited count, and gpkgUrl for each version
```

```gherkin
Given I download edit_v2
When the browser requests the gpkgUrl
Then the downloaded file is the edited GeoPackage for version 2 and the raw Model.gpkgUrl is unchanged
```

**UI Wireframe:** Version history list in the right panel. The API returns each
version's `gpkgUrl`; a dedicated one-click UI download action is a follow-up in
the current branch.

**Notes:** Assessment report, validation report, publishing, and visualizer use
of edited versions is out of scope for this feature.

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
| US-001 | `ui` | `ui-validation` | UI route and button gating only. |
| US-002 | `backend-dev`, `gis` | `backend-validation` | Queue/API ownership is backend; PMTiles, GeoPackage, CRS, and row-order checks require GIS review. |
| US-003 | `ui` | `ui-validation` | UI editor behavior; GIS should be consulted for class semantics but does not own UI code. |
| US-004 | `backend-dev`, `gis` | `backend-validation` | Version metadata plus GeoPackage read/write and row-order invariant. |
| US-005 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` | API version list and UI download history. |

### Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Phase 1 — Data Model & Artifact Contract | `backend-dev` | `gis` | `backend-validation` |
| Phase 2 — Prep Workflow & API | `backend-dev` | `gis` | `backend-validation` |
| Phase 3 — UI Editor | `ui` | `gis` | `ui-validation` |
| Phase 4 — Integration | `backend-dev` | `ui`, `gis` | `backend-validation`, `ui-validation` |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-001 | Phase 3 — UI Editor | `ui` | `ui/src/Components/` |
| P0 | US-002 | Phase 2 — Prep Workflow & API | `backend-dev`, `gis` | `hastelib`, `hastefuncapi`, `hastefuncqueues` |
| P0 | US-003 | Phase 3 — UI Editor | `ui` | `ui/src/Components/PredictionEditor/` |
| P0 | US-004 | Phase 1/2 — Data Model & API | `backend-dev`, `gis` | `hastelib`, Blob Storage, `hastefuncapi` |
| P1 | US-005 | Phase 4 — Integration | `backend-dev`, `ui` | `hastefuncapi`, `ui/src/Components/` |

## Out of Scope

Stories explicitly excluded from this feature:

- [ ] Use edited versions in assessment reports.
- [ ] Use edited versions in validation reports.
- [ ] Publish edited versions through the data-publishing workflow.
- [ ] Show edited versions in the general visualizer.
- [ ] Add collaborative real-time editing, locking, or audit diff playback.
- [ ] Introduce a generic artifact registry beyond the Model-level edited version list.
