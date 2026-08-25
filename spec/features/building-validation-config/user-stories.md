# User Stories: Building Validation configuration

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Domain expert who validates building damage on satellite imagery | Control how much validation work to take on; never lose completed work |
| Project Manager | Oversees a disaster response project | Trustworthy accuracy figures in the Validation and Assessment reports |

---

## Stories

### US-001: Configure how many buildings to validate

**As a** disaster analyst,
**I want to** set how many building footprints the validation workflow asks me
to label,
**So that** I can spot-check a layer quickly or validate it thoroughly, instead
of always being handed exactly 200.

**Priority:** P2
**Component(s):** `ui/src/Components/BuildingValidation`, `ui/src/Components/ProjectManagement/LayerRow.jsx`, `api/hastefuncapi`, `hastelib`

**Acceptance Criteria:**

```gherkin
Given an image layer with building footprints
When I click the gear icon beside its Building Validation "Launch" button
Then a modal opens showing the current count, defaulting to 200
```

```gherkin
Given the modal is open
When I enter 500 and save
Then the setting persists for that image layer
And launching Building Validation presents 500 buildings
```

```gherkin
Given an image layer with no building footprints
When I look at its Building Validation cell
Then the gear icon is disabled, like the Launch button
```

**Notes:** Range is 1–2000; 2000 is the existing server-side clamp in
`GetBuildingFootprintsGeoJSON`.

---

### US-002: Raise the count without losing labeling work

**As a** disaster analyst who has already labeled part of a validation set,
**I want** a larger count to add buildings rather than reshuffle them,
**So that** the work I have already done still counts.

**Priority:** P0 — this is the story that makes the feature safe.
**Component(s):** `hastelib/src/hastegeo/core/utils/footprints.py`, `api/hastefuncapi`

**Acceptance Criteria:**

```gherkin
Given a layer configured at 200 buildings, of which I have labeled 40
When I raise the count to 300
Then the same 200 buildings are still in the set, with my 40 labels intact
And 100 buildings I have not seen before are added
```

```gherkin
Given a layer configured at 200 buildings with no labels
When I raise the count to 300
Then the set grows to 300 with no reshuffle
```

**Notes:** Falls out of the fixed-seed permutation-prefix sampling. See
[design.md](design.md#why-growing-the-sample-is-free).

---

### US-003: Be stopped from silently discarding labeled buildings

**As a** disaster analyst,
**I want** to be refused when I lower the count while labels exist,
**So that** I cannot destroy my own validation work with a number change.

**Priority:** P0
**Component(s):** `api/hastefuncapi`, `ui/src/Components/BuildingValidation`

**Acceptance Criteria:**

```gherkin
Given a layer configured at 300 buildings, of which I have labeled 40
When I lower the count to 100 and save
Then the save is refused
And I am told to clear my validation labels first
And the stored count stays at 300
```

```gherkin
Given a layer configured at 300 buildings with no labels
When I lower the count to 100 and save
Then the change is accepted and the set is resampled to 100
```

---

### US-004: Clear validation labels

**As a** disaster analyst,
**I want to** clear all validation labels for a layer,
**So that** I can start the validation over — including after being blocked by
US-003.

**Priority:** P1
**Component(s):** `ui/src/Components/BuildingValidation`

**Acceptance Criteria:**

```gherkin
Given a layer with validation labels
When I choose "Clear all validation labels" in the config modal or in the
  validation view's right panel
Then I am asked to confirm before anything is deleted
```

```gherkin
Given I confirm the clear
When the operation completes
Then the layer has no validation labels
And the configured count is unchanged
```

---

### US-005: Keep the configured count across label saves

**As a** disaster analyst,
**I want** saving my labels to leave my configured count alone,
**So that** the setting does not quietly revert to 200 while I work.

**Priority:** P0
**Component(s):** `api/hastefuncapi`

**Acceptance Criteria:**

```gherkin
Given a layer configured at 500 buildings
When the validation view saves labels with a payload that carries no sampleSize
Then the stored sampleSize is still 500
```

**Notes:** Guards against the wholesale-replace hazard described in
[design.md](design.md#the-data-loss-hazard-this-design-must-avoid); the same
failure mode as PR #135.

---

## Agent Assignment Map

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend, API, models, utils | Yes |
| `ui` | React/FluentUI frontend | Yes |
| `backend-validation` | Validates backend against spec, conventions, tests | No |
| `ui-validation` | Validates frontend behavior | No |
| `orchestrator` | Records what was done, when, why | No |

### Story → Agent Mapping

| Story | Implementing agent | Validating agent |
|---|---|---|
| US-001 | `backend-dev` (model, config route), `ui` (modal, gear entry points) | `backend-validation`, `ui-validation` |
| US-002 | `backend-dev` (`sample_indices`, endpoint wiring) | `backend-validation` |
| US-003 | `backend-dev` (rules in `PutBuildingValidationConfig`), `ui` (mirrored feedback) | `backend-validation`, `ui-validation` |
| US-004 | `ui` (modal + right-panel controls, confirms) | `ui-validation` |
| US-005 | `backend-dev` (merge-preserving `PutBuildingValidation`) | `backend-validation` |

No `gis` involvement: the footprints are read through the existing GeoPackage
path and no geospatial logic changes. No new dependencies, so no `security`
involvement.
