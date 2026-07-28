# Execution Plan: Open Data Catalog Explorer

> Status reflects work already implemented on the `feat-data-catalog*` branches.

## Phases

### Phase 1: Core Library — done

**Goal:** allowlist + clip plumbing in `hastelib`.

| Task | Agent | Story | Status |
|---|---|---|---|
| Allow `data.source.coop` in `url_allowlist` + `validate_clip_bbox` (+ tests) | `backend-dev`/`gis` | US-004 | done |
| `ImageLayer.clipBbox` model field | `backend-dev` | US-004 | done |
| `mosaic_imagery(..., clip_bbox)` → gdalwarp `-te`/`-te_srs` | `gis` | US-004 | done |
| Route non-S3/Blob allowlisted hosts through generic HTTP downloader | `gis` | US-004 | done |

**Exit Criteria:** [x] unit tests pass; [x] clip applies independently of the API.

### Phase 2: API Layer — done

**Goal:** carry + validate `clipBbox`; thread into imagery prep.

| Task | Agent | Story | Status |
|---|---|---|---|
| `PutLayer` validates + persists `clipBbox` | `backend-dev` | US-004 | done |
| `clip_bbox` into imagery-prep config; `ImageryWorkflow` → `_create_mosaic_cog` | `backend-dev`/`gis` | US-004 | done |

**Exit Criteria:** [x] end-to-end prep run clips to the AOI in Docker Compose.

### Phase 3: UI — done

**Goal:** the catalog experience.

| Task | Agent | Story | Status |
|---|---|---|---|
| `openDataCatalog.js` discovery/normalization + TiTiler/AOI helpers | `ui` | US-001 | done |
| Panel + Map + SceneListItem (footprints, preview, filters) | `ui` | US-001/002 | done |
| Add scene → pre/post with auto-fill; phase-scoped buttons | `ui` | US-003 | done |
| Clip drawing + layer `clipBbox`; AOI-overlap filter + "covers AOI" badge | `ui` | US-004/005 | done |
| Preview loading indicator; two-way map↔list selection | `ui` | US-002/006 | done |

**Exit Criteria:** [x] feature usable in the SWA/Docker local stack.

### Phase 4: Integration & Deployment — partial

| Task | Agent | Status |
|---|---|---|
| Local nginx proxy: titiler timeouts + `client_max_body_size` | `backend-dev` | done |
| E2E validation in Docker Compose | `backend-dev` | done |
| Deploy to dev1/testing/prod SWA + Function Apps | `backend-dev` | not-started |
| Docs / CHANGELOG | `backend-dev` | not-started |

## Milestones

| Milestone | Status | Deliverable |
|---|---|---|
| Core library done | done | allowlist + clip in `hastelib` |
| API layer done | done | `PutLayer` + prep config |
| UI done | done | catalog visible in the app |
| Release | not-started | deployed to production SWA |

## Agent Summary

| Agent | Phases |
|---|---|
| `gis` | 1, 2 |
| `backend-dev` | 1, 2, 4 |
| `ui` | 3 |

## Resource Requirements

- **Azure services:** none new (reuses TiTiler, Blob, queues, imageryprep image).
- **External data:** Vantor Open Data (S3), Planet Open Data (Source Cooperative). Both public, CC BY-NC 4.0.

## Open Questions

- [ ] Production rollout + any provider-catalog change monitoring.
