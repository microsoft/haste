# Technical Design: Open Data Catalog Explorer

## Overview

A Fluent UI side panel on the Create Image Layer page browses open imagery
(Vantor/Maxar S3 STAC + Planet Source-Cooperative STAC), previews scenes on an
Azure Maps map via TiTiler, and adds scene COG URLs into the layer's pre/post
imagery. A drawn clip AOI is stored on the layer and applied server-side by the
imagery-prep workflow. The reference prototype is the standalone Open Disaster
Response Data Visualizer:
<https://visualizers.aiforgood.ai/damage-assessment/venezuela_earthqake_data_explorer.html>

## Architecture

### Component Diagram

```
┌───────────────────────────┐   direct HTTPS (CORS *)    ┌──────────────────────────┐
│  React UI                 │───────────────────────────▶│ Vantor S3 STAC           │
│  OpenDataCatalog panel    │                            │ Planet source.coop STAC  │
│  (Fluent UI + Azure Maps) │◀──── COG tiles/crop ───────│ TiTiler (api/titiler)    │
└─────────────┬─────────────┘   via /api/titiler proxy   └──────────────────────────┘
              │ PutLayer (clipBbox + COG URLs)
              ▼
   ┌────────────────────┐   queue msg   ┌────────────────────┐   docker run   ┌──────────────────┐
   │  hastefuncapi       │──────────────▶│  hastefuncqueues    │───────────────▶│ haste-imageryprep │
   │  PutLayer (validate)│               │  LocalRunner/Batch  │                │ prepare_imagery   │
   └────────────────────┘               └────────────────────┘                └────────┬─────────┘
                                                                                        │ gdalwarp -te (clip)
                                                                                        ▼ Blob (clipped COGs)
```

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Catalog module | `ui/src/Components/OpenDataCatalog/openDataCatalog.js` | Framework-free discovery + STAC normalization + TiTiler URL builders + AOI geometry helpers | JS |
| Catalog panel | `ui/src/Components/OpenDataCatalog/OpenDataCatalogPanel.jsx` | Fluent `<Panel>`: event picker, filters, list + map, clip toolbar | React / Fluent UI |
| Catalog map | `ui/src/Components/OpenDataCatalog/OpenDataCatalogMap.jsx` | Azure Maps footprints, TiTiler COG preview, rectangle clip drawing, loading indicator | React / Azure Maps |
| Scene row | `ui/src/Components/OpenDataCatalog/SceneListItem.jsx` | One scene: thumbnail, badges, expandable metadata, phase-scoped add buttons | React / Fluent UI |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| Image layer form | `ui/src/Components/CreateEditImageLayerForm.jsx` | "Browse Open Data Catalog" button + panel; `handleAddScene`, `handleClipAoiChange`; `clipBbox` in PutLayer body |
| Form helper | `ui/src/Components/CreateEditImageLayerHelper.js` | `addSceneToEventImagery()`; `clipBbox` in default state |
| Imagery allowlist (UI) | `ui/src/util/validation.js` | allow `data.source.coop` |
| Imagery allowlist (backend) | `hastelib/.../core/utils/url_allowlist.py` | allow `data.source.coop`; `validate_clip_bbox` |
| Downloader | `hastelib/.../core/utils/downloader.py` | route non-S3/Blob allowlisted hosts through generic HTTP |
| Mosaic | `hastelib/.../core/utils/imagery.py` | `mosaic_imagery(..., clip_bbox)` → gdalwarp `-te`/`-te_srs` |
| Imagery processor | `hastelib/.../core/processors/imagery.py` | `clip_bbox` in the prep config |
| Prep workflow | `hastelib/.../workflows/prepare_imagery.py` | thread `clip_bbox` through `ImageryWorkflow` → `_create_mosaic_cog` |
| Image layer model | `hastelib/.../core/models/projects.py` | `ImageLayer.clipBbox` |
| PutLayer | `api/hastefuncapi/function_app.py` | `validate_clip_bbox` |
| Dev proxy | `docker/nginx.conf` | `/api/titiler` timeouts (300s) + `client_max_body_size 64m` |

## Event discovery & scene normalization

Both catalogs are STAC. `openDataCatalog.js` exposes two contracts:

- `discoverEvents()` → `{ events, errors }`. Crawls two root catalogs and
  merges events present in both:
  - **Vantor:** `https://vantor-opendata.s3.amazonaws.com/events/catalog.json`
    → `child` links → each event `collection.json` (id, `odp:event_date`,
    `item` links).
  - **Planet:** `https://data.source.coop/planet/disasterdata/catalog.json`
    → `child` links → each event `catalog.json` → `pre-event`/`post-event`
    collections → items (or a pre-event `mosaic` asset).
  - **Merge:** event ids are tokenized into place vs hazard words (dates/months
    dropped); two events merge when their place tokens overlap and hazards
    agree (e.g. Vantor `Venezuela-Earthquake-Jun-2026` ↔ Planet
    `venezuela-earthquake-2026-06-24`). Each unified event carries
    `sources: { vantor?, planet? }`.
- `fetchEventCatalog(event)` → `{ scenes, errors }`. Fetches whichever sources
  the event has, resiliently (a failing source is dropped with a warning), and
  dedupes + assigns a unique `uid`.

Scene model — see [data-model.md](data-model.md#normalized-scene-in-memory-ui-only).
Vantor items carry an explicit `phase` property and a `visual` COG asset;
Planet phase comes from the `pre-event`/`post-event` collection id.

## Map: preview, clip, indicators (Azure Maps + TiTiler)

- **Footprints:** a `DataSource` + `PolygonLayer` (fill) + `LineLayer` (outline),
  colored by source, highlight driven by an `_active` feature property.
- **COG preview:** selecting a scene adds an `atlas.layer.TileLayer` pointed at
  `titilerTileUrl(cogUrl)` → `/cog/tiles/{z}/{x}/{y}.png?url=…`, inserted
  beneath the footprint layers. Works with **no Azure Maps subscription**
  (blank basemap) because the imagery itself is served by TiTiler.
- **Loading indicator:** the preview TileLayer is given id `odcPreview`; its GL
  source id is resolved via a `findGlMap` duck-type, and a `sourcedata` /
  `isSourceLoaded` listener clears a "Loading imagery…" chip once its tiles are
  in (15s timeout fallback).
- **Clip drawing:** `atlas.drawing.DrawingManager` in `draw-rectangle` mode;
  on completion the EPSG:4326 bbox is handed up and rendered as a persistent
  dashed AOI rectangle.
- **Two-way selection:** clicking a footprint selects the scene (list scrolls to
  it, highlights, expands metadata). During preview the fill is set fully
  transparent (not hidden) so footprints stay clickable to switch scenes.

TiTiler is reached from the browser through the api-proxy at `VITE_TITILER_URL`
(`…/api/titiler/`). Both source catalogs send `Access-Control-Allow-Origin: *`,
so browser fetches and tiles work directly.

## Clip approaches

Two were built; the **server-side** approach is the current direction.

### Server-side clip (current)

A single **layer-level** `clipBbox` (`[west, south, east, north]`, EPSG:4326) is
drawn in the catalog and stored on the `ImageLayer`. Because it applies to both
pre and post mosaics, the catalog filters scenes to those overlapping the AOI
(`bboxIntersects`) and badges scenes that fully contain it (`bboxContains`).

Flow: draw AOI → `PutLayer` carries `clipBbox` → prep config `clip_bbox` →
`ImageryWorkflow` → `_create_mosaic_cog(..., clip_bbox)` →
`mosaic_imagery(..., clip_bbox)` appends `-te <w> <s> <e> <n> -te_srs EPSG:4326`
to the gdalwarp options. GDAL reprojects the EPSG:4326 bounds to the mosaic's
CRS, so no manual reprojection is needed. The AOI polygon + Overture footprints
are then derived from the already-clipped mosaic.

### Client-side clip (prototype, sibling branch)

Draw box → TiTiler `/cog/crop/{minx},{miny},{maxx},{maxy}/{w}x{h}.tif?url=…`
returns a clipped GeoTIFF → wrapped as a `File` → uploaded via the existing
chunked uploader → added as a normal blob URL. Instant clip visibility but a
download→reupload round-trip and a client-side wait. Superseded by the
server-side approach for the AOI-per-layer model.

## API Design

### `PUT /api/PutLayer` (modified)

Adds one optional field on the `ImageLayer` request body:

```json
{
  "clipBbox": "[number, number, number, number] | null — [west, south, east, north] EPSG:4326"
}
```

Validated by `validate_clip_bbox` (in `url_allowlist.py`): must be 4 finite
numbers, lon in [-180,180], lat in [-90,90], `west<east`, `south<north`;
otherwise **400**. Imagery URLs continue to be checked by
`validate_image_layer_imagery_urls` (now allowing `data.source.coop`).

### Queue message (unchanged shape) + prep config

`ImageryPostProcessor` adds `clip_bbox` to the YAML imagery-prep config passed
to the `prepare-imagery` container; `prepare_imagery.main()` reads it and passes
it to `ImageryWorkflow(clip_bbox=…)`.

### Internal interfaces (hastegeo)

| Module | Function | Signature | Description |
|---|---|---|---|
| `core/utils/url_allowlist.py` | `validate_clip_bbox(image_layer)` | `-> Optional[str]` | None if valid/absent, else user-facing error |
| `core/utils/imagery.py` | `ImageryUtils.mosaic_imagery` | `(tif_files, output_file_path, gdal_warp_params, clip_bbox=None)` | Appends `-te`/`-te_srs` when `clip_bbox` set |
| `core/utils/downloader.py` | `ImageryDownloader.download_imagery` | routes `sourcecoop`/other allowlisted hosts to `download_imagery_from_urls` | generic streamed HTTPS + size cap |
| `workflows/prepare_imagery.py` | `ImageryWorkflow.__init__` / `_create_mosaic_cog` | `clip_bbox=None` | threaded to `mosaic_imagery` |

## Behavior & Logic

### Core flow (add a scene)

1. Analyst opens the catalog on the Create Image Layer page.
2. `discoverEvents()` lists events; selecting one runs `fetchEventCatalog()`.
3. Analyst previews scenes (TiTiler) and optionally draws a clip AOI.
4. Phase-scoped **＋ Pre/＋ Post** appends the COG URL (auto-fills source-type +
   date); the AOI sets `clipBbox`.
5. Submit → `PutLayer` validates URLs + `clipBbox`, enqueues imagery prep.
6. `hastefuncqueues` spawns `haste-imageryprep`; the mosaic is clipped to the AOI.

### Edge Cases

| Case | Expected Behavior |
|---|---|
| One source catalog fails (CORS/network) | Other source's scenes still load; per-source warning banner |
| Duplicate STAC ids across a catalog | Deduped by `source + cogUrl`; unique `uid` for keys/features |
| Scene has no COG (footprint only) | Add buttons disabled; "COG not linked yet" note; no preview |
| Clip AOI doesn't overlap a scene | Scene hidden by the "only scenes in clip area" filter (default on) |
| No Azure Maps key (placeholder) | Blank basemap; footprints + TiTiler preview still work |
| Planet `data.source.coop` imagery | Downloaded via generic HTTP route (not S3/Blob SDK) |
| Large clip / slow TiTiler crop (client approach) | 4096px cap + client timeout; nginx 300s + friendly 504 msg |

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `VITE_TITILER_URL` | url | `…/api/titiler/` | `docker-compose.yml` (ui) | Browser-reachable TiTiler base for preview/clip |
| `VITE_AZURE_MAPS_CLIENT_ID` | uuid | `placeholder` | `docker-compose.yml` (ui) | Azure Maps anonymous/AAD Client ID; placeholder → blank basemap (footprints + TiTiler preview still work) |
| `CLEANUP_CONTAINERS` | bool | `1` | `docker-compose.yml` (queues) | Debug: retain a failed spawned container's logs |
| `client_max_body_size` / `proxy_read_timeout` | nginx | `64m` / `300s` | `docker/nginx.conf` | Chunk uploads + titiler crop headroom (local dev) |

## Observability

- UI: per-source discovery/fetch error banners; preview loading chip.
- Backend: structured logging in `prepare_imagery` (`Clipping mosaic to AOI bbox …`); layer `statusMessage` surfaces failures.

## Open Questions

- [ ] Move discovery/normalization behind an Azure Function (`GetOpenDataCatalog`)? The module contract is designed for it.
- [ ] Polygon-exact (vs bbox) overlap filtering for oblique footprints?
- [ ] Hard backend guard for pre/post correctness (UI-only today)?
