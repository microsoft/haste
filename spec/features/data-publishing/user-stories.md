# User Stories: Data Publishing & Published Datasets

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Domain expert who runs training/inference and interprets damage results | Turn a finished result into a stable, shareable, described dataset without hand-authoring metadata |
| Project Manager | Oversees a response project and its outputs | A single place to see what's been published for the event, and where |
| External Partner / Data Consumer | Downstream user (agency, NGO, researcher) | Discover finished HASTE datasets and retrieve them, ideally via standards (STAC) they already use |
| Admin | Configures system settings, base models, source types, and now publishing targets | Enable/disable providers, set the Planetary Computer GeoCatalog endpoint + credentials |

> The **ML Engineer** persona from the template is out of scope — publishing acts
> on *finished* artifacts, not the training workflow.

---

## Stories

### US-001: Publish a dataset from model results

**As a** Disaster Analyst,
**I want to** click **Publish dataset** on a completed model's results and fill a short form,
**So that** the model's outputs become a named, described, discoverable dataset instead of a one-off download link.

**Priority:** P0
**Estimate:** L
**Component(s):** `ui/src/Components/ProjectManagement/ModelResultsButton.jsx`, `ui/src/Components/PublishDatasetModal.jsx`, `api/hastefuncapi` (`PutPublishDatasetQueueMessage`)

**Acceptance Criteria:**

```gherkin
Given a model whose inference has completed and produced a GeoPackage
When I open the model's results menu
Then I see a "Publish dataset…" action alongside the download actions
```

```gherkin
Given I open the Publish dataset dialog
When the dialog loads
Then the Dataset name is pre-filled with "<project name> – <layer name>"
  And the Description is pre-filled from the assessment report summary (when available)
  And an "Assets to publish" checklist shows the model's available outputs, all prechecked
  And the Target publishing location dropdown lists "Local" and "Planetary Computer"
```

```gherkin
Given I have edited the name and chosen a target
When I click Publish
Then a PublishedDataset record is created with status PENDING
  And a message is enqueued to the publish-queue
  And the dialog confirms "Publishing started" and closes
```

**UI Wireframe:** see [ux-spec.md](ux-spec.md#publish-dataset-dialog).

**Notes:** Publish action is disabled (with tooltip) unless the model has at
least one publishable artifact (e.g. `gpkgUrl`) and status is completed.

---

### US-002: Browse the Published Datasets section

**As a** Project Manager,
**I want to** open a **Published Datasets** section and see every published dataset,
**So that** I have one authoritative view of the event's finished outputs and where each was published.

**Priority:** P0
**Estimate:** M
**Component(s):** `ui/src/Components/PublishedDatasets.jsx`, `PublishedDatasetRow.jsx`, `api/hastefuncapi` (`GetPublishedDatasets`)

**Acceptance Criteria:**

```gherkin
Given one or more datasets have been published
When I navigate to Published Datasets
Then I see a searchable, sortable, paginated list showing name, project/layer,
     target, status, published-by, and published date
```

```gherkin
Given no datasets have been published yet
When I open Published Datasets
Then I see an empty state explaining how to publish from model results
```

```gherkin
Given a dataset is still publishing
When I view the list
Then that row shows an in-progress indicator and no broken retrieval links
```

**Notes:** Mirror `ModelCatalog.jsx` (search box, `PAGE_SIZE_OPTIONS`, sort
state, `pgrid-*` layout, `NoResultsMessage`). Optional `projectId` query param
lets the section be filtered to one project.

---

### US-003: Publish to Local HASTE storage

**As a** Disaster Analyst,
**I want to** publish to **Local** (HASTE storage),
**So that** the dataset is registered and retrievable inside HASTE even if the source model is later re-run or deleted.

**Priority:** P0
**Estimate:** M
**Component(s):** `hastelib/.../core/publishing/local_provider.py`, `hastefuncqueues`

**Acceptance Criteria:**

```gherkin
Given I publish a completed model to the Local target
When the publish-queue worker runs the Local provider
Then the model's artifacts are copied to published/{datasetId}/ in HASTE storage
  And the dataset record gains stable retrieval links + status PUBLISHED
  And the dataset is visible in the Published Datasets section
```

```gherkin
Given the source model is deleted after publishing
When I retrieve the published dataset
Then its links still resolve (published copy is independent)
```

**Notes:** Published copies are immutable (copy-on-publish) for lifecycle
independence; total copied bytes are bounded by `PUBLISH_MAX_TOTAL_BYTES`.

---

### US-004: Publish to Planetary Computer (STAC)

**As a** Disaster Analyst,
**I want to** publish to **Planetary Computer**,
**So that** HASTE outputs are catalogued as STAC and discoverable/tileable in the broader geospatial ecosystem.

**Priority:** P1
**Estimate:** XL
**Component(s):** `hastelib/.../core/publishing/planetary_computer_provider.py`, `core/publishing/stac.py`, `hastefuncqueues`

**Acceptance Criteria:**

```gherkin
Given the Planetary Computer provider is configured (GeoCatalog URL + credential + ingestion source)
When I publish a dataset to the Planetary Computer target
Then a STAC Collection for the project is created (or reused) via /stac/collections
  And STAC Item(s) for the dataset's artifacts are POSTed to /stac/collections/{id}/items
  And the worker polls the returned ingestion location until it reaches a terminal state
  And the dataset record stores the collection id, item ids, and explorer links with status PUBLISHED
```

```gherkin
Given the GeoCatalog rejects an item (validation / 40x) or ingestion fails
When the worker processes the failure
Then the dataset status becomes FAILED with a human-readable statusMessage
  And no partial/broken links are surfaced in the UI
```

**Notes:** STAC Item ids must avoid `-_+().` (GeoCatalog restriction) — see
[design.md](design.md#planetary-computer-provider--stac-mapping). Assets reference HASTE blob URLs; the
GeoCatalog copies them via the pre-registered ingestion source.

---

### US-005: Retrieve, inspect, and unpublish a dataset

**As an** External Partner / Data Consumer,
**I want to** open a published dataset's detail and retrieve its artifacts or STAC links,
**So that** I can consume the finished output; and as an owner/admin I want to **unpublish** it.

**Priority:** P1
**Estimate:** M
**Component(s):** `ui/src/Components/PublishedDatasetRow.jsx` (detail/menu), `api/hastefuncapi` (`GetPublishedDataset`, `DeletePublishedDataset`)

**Acceptance Criteria:**

```gherkin
Given a PUBLISHED dataset
When I open its detail/actions
Then I can download each Local artifact and/or follow the Planetary Computer collection link
```

```gherkin
Given I am the publisher or an admin
When I choose Unpublish
Then the record is removed from the section
  And Local published copies are cleaned up
  And (for Planetary Computer) the collection/items are deleted via the STAC API (best-effort, logged)
```

**Notes:** Unpublish permission = publisher or admin (see
[ux-spec.md](ux-spec.md#permissions--access-control) and README access
assumptions).

---

### US-006: Configure and select publishing providers

**As an** Admin,
**I want to** configure available providers and their requirements,
**So that** analysts only see targets that are actually usable, with clear validation.

**Priority:** P2
**Estimate:** S
**Component(s):** `api/hastefuncapi` (`GetPublishingProviders`), `core/publishing/registry.py`, `config.py`

**Acceptance Criteria:**

```gherkin
Given the Planetary Computer GeoCatalog settings are not configured
When an analyst opens the target dropdown
Then Planetary Computer is shown as disabled with a "not configured" note
  And Local remains available
```

```gherkin
Given a provider declares config requirements
When the UI renders the dialog
Then it surfaces provider-specific validation from GetPublishingProviders (no hard-coding per provider)
```

**Notes:** Provider metadata (id, display name, config requirements, async flag)
comes from the registry so the UI is provider-agnostic. In v1, the actual
configuration values (GeoCatalog URL, ingestion source, collection prefix) are
**Azure App Settings** set by an operator at deploy time — there is no in-app
provider-config screen. Credentials are managed identity only; this story is
about *reflecting* configuration state in the dialog, not entering it.

---

### US-007: Choose which outputs to publish

**As a** Disaster Analyst,
**I want to** select which of the model's existing outputs (damage GeoPackage,
valid mask, building footprints, processed image COG, …) are included,
**So that** I publish exactly the deliverables I intend to share and skip the rest.

**Priority:** P1
**Estimate:** S
**Component(s):** `ui/src/Components/PublishDatasetModal.jsx`, `api/hastefuncapi` (`PutPublishDatasetQueueMessage`), `core/publishing` (`ArtifactBundle`)

**Acceptance Criteria:**

```gherkin
Given the Publish dataset dialog is open for a model
When the asset checklist renders
Then it lists one checkbox per artifact the model actually produced (all prechecked)
  And artifacts the model did not produce are grayed/omitted
```

```gherkin
Given I uncheck some assets and leave at least one checked
When I publish
Then only the selected assets are copied (Local) or turned into STAC assets/items (Planetary Computer)
  And the PublishedDataset.artifacts records exactly the selected kinds
```

```gherkin
Given I uncheck every asset
When I try to publish
Then Publish is disabled with "Select at least one asset to publish"
  And a forced API call with an empty selection returns 400
```

**Notes:** Selection is sent as `artifacts: [...]` in the publish request;
`ArtifactBundle` is filtered to the selection before any provider runs (see
[design.md](design.md#publishing-provider-interface)).

---

## Agent Assignment Map

Every user story is assigned to one or more HASTE agents. The **implementing
agent** writes the code; the **validating agent** verifies against acceptance
criteria. See [Agent Architecture](../../architecture/overview.md#agent-architecture).

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend, API, processors, data layers, publishing providers | Yes |
| `gis` | STAC item/collection generation, GDAL/rasterio reads of COG/GPKG | Yes |
| `ui` | React/FluentUI section + dialog, sidebar/routing | Yes |
| `security` | New Python deps (`azure-identity`, `pystac`, `geopandas`, `pyogrio`, `shapely`), credential handling | No (reports only) |
| `backend-validation` | Validates backend/provider code against specs, conventions, tests | No (validates only) |
| `ui-validation` | Validates section + dialog behavior and states | No (validates only) |
| `security-validation` | Validates security findings | No (validates only) |
| `orchestrator` | Tracks spec status and agent work | No (observes only) |

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` | Dialog + enqueue endpoint |
| US-002 | `ui` | `ui-validation` | Catalog-style section |
| US-003 | `backend-dev` | `backend-validation` | Local provider + worker |
| US-004 | `gis`, `backend-dev` | `backend-validation`, `security-validation` | STAC + PC provider + creds |
| US-005 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` | Retrieve + unpublish |
| US-006 | `backend-dev`, `ui` | `backend-validation` | Provider metadata/registry |
| US-007 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` | Asset selection in dialog + request |

> **Rules:** every story has ≥1 implementing + ≥1 validating agent; `hastelib`/`api`
> → `backend-dev`+`backend-validation`; STAC/imagery reads → `gis`; `ui/` →
> `ui`+`ui-validation`; new deps → `security`+`security-validation`.

### Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Phase 1 — Core Library (models, provider ABC, Local, STAC) | `backend-dev` | `gis` | `backend-validation` |
| Phase 2 — API + Queue | `backend-dev` | — | `backend-validation` |
| Phase 3 — Planetary Computer provider | `gis` | `backend-dev`, `security` | `backend-validation`, `security-validation` |
| Phase 4 — UI | `ui` | — | `ui-validation` |
| Phase 5 — Integration & Deployment | `backend-dev` | `ui` | `backend-validation`, `ui-validation` |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-001 | Phase 4 — UI (+ Phase 2 API) | `ui`, `backend-dev` | `ui/`, `hastefuncapi` |
| P0 | US-002 | Phase 4 — UI | `ui` | `ui/src/Components/` |
| P0 | US-003 | Phase 1/2 — Core + Queue | `backend-dev` | `core/publishing/local_provider.py` |
| P1 | US-004 | Phase 3 — PC provider | `gis`, `backend-dev` | `core/publishing/planetary_computer_provider.py` |
| P1 | US-005 | Phase 2/4 — API + UI | `ui`, `backend-dev` | `hastefuncapi`, `ui/` |
| P2 | US-006 | Phase 2/4 — API + UI | `backend-dev`, `ui` | `core/publishing/registry.py` |
| P1 | US-007 | Phase 4 — UI (+ Phase 2 API) | `ui`, `backend-dev` | `ui/`, `hastefuncapi` |

## Out of Scope

- [ ] Publishing arbitrary user uploads (only HASTE-generated artifacts of a
      project/layer/model are publishable in v1).
- [ ] Versioning / re-publishing history beyond a single current record per
      dataset (a re-publish overwrites/updates; no version tree).
- [ ] Access-control sharing lists per dataset (public-within-tenant only in v1;
      no per-user ACLs).
- [ ] Additional providers (ArcGIS, generic STAC API, DOI/Zenodo) — the interface
      supports them but none are built in v1.
- [ ] Editing STAC metadata by hand in the UI (generated from artifacts +
      assessment report only).
- [ ] In-app admin screen for configuring publishing targets — v1 configures
      providers via Azure App Settings + managed identity (operator/deploy-time).
      A future admin UI can slot behind the existing `ProviderInfo` contract
      without UI/API rework.
