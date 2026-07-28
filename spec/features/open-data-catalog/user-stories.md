# User Stories: Open Data Catalog Explorer

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Domain expert who assembles imagery and produces damage maps | Find the right open imagery for an event fast; get a clean AOI |

---

## Stories

### US-001: Browse open disaster imagery in-app

**As a** Disaster Analyst,
**I want to** browse open imagery for a disaster event from within the Create Image Layer page,
**So that** I don't have to hunt for COG URLs on external S3/STAC catalogs.

**Priority:** P1 · **Component(s):** `ui/src/Components/OpenDataCatalog/`

```gherkin
Given I am on the Create Image Layer page
When I click "Browse Open Data Catalog"
Then I see a panel listing every disaster event discovered across Vantor and Planet
And events present in both sources are shown once, tagged "Vantor + Planet"
```

```gherkin
Given one source catalog is unreachable
When the catalog loads
Then the other source's scenes still appear
And a per-source warning banner explains what failed
```

---

### US-002: Preview a scene's imagery on the map

**As a** Disaster Analyst,
**I want to** preview a scene's actual imagery on the map,
**So that** I can judge coverage/quality before adding it.

**Priority:** P1 · **Component(s):** `OpenDataCatalog/OpenDataCatalogMap.jsx`

```gherkin
Given a scene with a COG is listed
When I select it
Then its imagery streams onto the map via TiTiler and the view flies to it
And a "Loading imagery…" indicator shows until its tiles have rendered
```

```gherkin
Given Azure Maps is in placeholder mode (no real Client ID configured)
When I preview a scene
Then the imagery still renders (on a blank basemap)
```

---

### US-003: Add a scene to the correct phase

**As a** Disaster Analyst,
**I want to** add a scene to pre- or post-event imagery in one click,
**So that** the layer is populated correctly without copy/paste.

**Priority:** P0 · **Component(s):** `OpenDataCatalog/SceneListItem.jsx`, `CreateEditImageLayerHelper.js`

```gherkin
Given a scene whose phase is "post"
When I look at its actions
Then only "＋ Post-event" is offered (not "＋ Pre-event")
When I click it
Then the COG URL is appended to post-event imagery and source-type + capture date are auto-filled when empty
```

```gherkin
Given a scene already added to post-event
When I view it
Then its button shows "Added to Post" and is disabled
```

---

### US-004: Clip imagery to a drawn AOI

**As a** Disaster Analyst,
**I want to** draw an area on the map and have the produced imagery clipped to it,
**So that** the layer covers only the area I care about.

**Priority:** P1 · **Component(s):** `OpenDataCatalogMap.jsx`, `hastelib` imagery prep

```gherkin
Given I have selected a scene
When I click "Set clip area" and drag a box
Then a persistent AOI rectangle is drawn and stored on the layer (clipBbox)
When the image layer is processed
Then the pre/post mosaics are clipped to that AOI (gdalwarp -te) and the derived AOI/footprints cover only the clipped area
```

```gherkin
Given a clipBbox with west>=east or out-of-range coordinates
When I submit the layer
Then PutLayer returns 400 with a clear message
```

---

### US-005: Keep pre/post on the same AOI

**As a** Disaster Analyst,
**I want to** see only scenes that cover my clip area when picking pre and post,
**So that** both phases share the same AOI and nothing clips away to nothing.

**Priority:** P2 · **Component(s):** `OpenDataCatalogPanel.jsx`

```gherkin
Given I have drawn a clip AOI
When I browse scenes
Then by default only scenes whose footprint overlaps the AOI are shown
And scenes whose footprint fully contains the AOI get a "covers AOI" badge
And I can toggle the filter off to see all scenes
```

---

### US-006: Select from the map and see it in the list

**As a** Disaster Analyst,
**I want to** click a footprint on the map and have the list jump to that scene,
**So that** I can browse spatially and still see the scene's details/actions.

**Priority:** P2 · **Component(s):** `OpenDataCatalogMap.jsx`, `OpenDataCatalogPanel.jsx`, `SceneListItem.jsx`

```gherkin
Given several footprints are on the map
When I click one (including while another scene is previewing)
Then that scene is selected: the list scrolls to it, highlights it, and expands it with extra metadata
```

---

## Agent Assignment Map

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `gis` | Satellite imagery, GDAL/rasterio, provider adapters | Yes |
| `backend-dev` | Python backend, API, processors, data layers | Yes |
| `ui` | React/FluentUI/Azure Maps, frontend | Yes |
| `backend-validation` | Validates backend against specs/tests | No |
| `ui-validation` | Validates frontend behavior | No |

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `ui` | `ui-validation` | STAC discovery in a UI module |
| US-002 | `ui`, `gis` | `ui-validation` | TiTiler preview |
| US-003 | `ui` | `ui-validation` | phase-scoped add |
| US-004 | `gis`, `backend-dev` | `backend-validation` | mosaic clip + PutLayer |
| US-005 | `ui` | `ui-validation` | AOI overlap filter |
| US-006 | `ui` | `ui-validation` | two-way selection |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-003 | Phase 3 — UI | `ui` | `ui/src/Components/OpenDataCatalog/` |
| P1 | US-001 | Phase 3 — UI | `ui` | `ui/src/Components/OpenDataCatalog/` |
| P1 | US-002 | Phase 3 — UI | `ui`/`gis` | `OpenDataCatalogMap.jsx` |
| P1 | US-004 | Phase 1/2 — Core/API | `gis`/`backend-dev` | `hastelib`, `hastefuncapi` |
| P2 | US-005 | Phase 3 — UI | `ui` | `OpenDataCatalogPanel.jsx` |
| P2 | US-006 | Phase 3 — UI | `ui` | `OpenDataCatalog/` |

## Out of Scope

- [ ] Live COG streaming preview with per-tile progress (reference used OpenLayers + geotiff); TiTiler tile preview is used instead.
- [ ] Hard backend enforcement of pre/post correctness (UI-guarded only).
- [ ] Per-scene (rather than layer-level) clip AOIs.
