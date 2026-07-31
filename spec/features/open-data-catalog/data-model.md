# Data Model: Open Data Catalog Explorer

> HASTE's local/dev stack stores image-layer metadata as JSON in Blob Storage
> (`METADATA_STORAGE_TYPE=blob`), not Cosmos DB. The "Cosmos" section below
> describes the logical `ImageLayer` document change; it applies equally to the
> blob-backed metadata store.

## Image Layer document change

### Modified schema

| Store | Field | Before | After | Notes |
|---|---|---|---|---|
| ImageLayer metadata | `clipBbox` | (absent) | `Optional[list[float]]` = `null` | `[west, south, east, north]` EPSG:4326. Optional, default `null`; fully backward compatible. |

```jsonc
// ImageLayer (relevant fields)
{
  "imageLayerId": "uuid",
  "projectId": "uuid",
  "preEventImageryUrls": ["https url", "..."],
  "postEventImageryUrls": ["https url", "..."],
  "sourceTypePreEvent": "maxar | planet_scope | planet_skysat | n/a | ...",
  "sourceTypePostEvent": "…",
  "clipBbox": [-66.859534, 10.4039, -66.816345, 10.424412]  // NEW, or null
}
```

**Migration needed?** No. New optional field; existing documents read as
`clipBbox=null` (no clip).

**RU / cost:** negligible — one small array field on an existing document.

## Imagery URL allowlist

Imagery URLs are validated (UI + backend) against a host allowlist. This
feature adds one host so Planet Open Data can be submitted:

| Host pattern | Source type label | Added |
|---|---|---|
| `*.blob.core.windows.net` | `azureblobstorage` | existing |
| `*.amazonaws.com` | `awss3` | existing (Vantor lives here) |
| `data.source.coop` / `*.source.coop` | `sourcecoop` | **new** |

Kept in sync between [`ui/src/util/validation.js`](../../../ui/src/util/validation.js)
and [`hastelib/.../core/utils/url_allowlist.py`](../../../hastelib/src/hastegeo/core/utils/url_allowlist.py).

## Normalized scene (in-memory, UI only)

Not persisted — produced by `openDataCatalog.js` from STAC, consumed by the
panel/map/list.

```js
{
  uid,                       // `${source}:${id}:${index}` — unique key/feature id
  id, source: "Vantor" | "Planet",
  phase: "pre" | "post" | null,
  cogUrl, thumbUrl,
  bbox, geometry,            // GeoJSON, EPSG:4326
  datetime,                  // ISO string
  title, place, sensor, constellation,
  gsd, cloud, offNadir, sunElev, cogSize,
  sourceUrl,                 // browse/attribution link
  sourceTypeKey,             // HASTE dropdown key: maxar | planet_scope | planet_skysat
}
```

## Blob Storage changes

No new containers. The imagery-prep workflow writes the same artifacts as
before (mosaic COG, processed RGB COG, valid-area-mask GeoJSON, building
footprints GPKG) under the existing per-layer path — but when `clipBbox` is set,
those artifacts cover only the clipped AOI.

```
{container=data}/
  {hash}/
    {task_id}/
      raw_imagery_post_event_mosaic_cog_{projectId}_{layerId}.tif   # clipped when clipBbox set
      processed_imagery_post_event_cog_{projectId}_{layerId}.tif
      valid_area_mask_{projectId}_{layerId}.geojson
      building_footprints_{projectId}_{layerId}.gpkg
```

## Queue Storage changes

No new queues and no message-shape change. `ImageryPostProcessor` adds
`clip_bbox` to the YAML imagery-prep **config** (blob-staged) that the
`prepare-imagery` container reads:

```yaml
project_id: "…"
image_layer_id: "…"
post_event_imagery_urls: ["https://data.source.coop/…/scene_visual.tif"]
source_type_post_event: "planet_scope"
clip_bbox: [-66.859534, 10.4039, -66.816345, 10.424412]   # NEW (null when unset)
```

## Data Flow

### Write path

```
UI → PutLayer (validate URLs + clipBbox) → ImageLayer metadata (Blob)
                                         → local-image-queue (job msg)
   hastefuncqueues → prepare-imagery (docker) → gdalwarp -te clip
                                              → Blob (clipped COGs + artifacts)
```

### Read path

```
UI → GetLayerDetailView → ImageLayer metadata (Blob)
UI catalog → Vantor S3 STAC / Planet source.coop STAC (direct HTTPS)
UI catalog → TiTiler (/api/titiler) → remote COG tiles/crop (preview)
```

## Migration Plan

### Forward

1. Deploy backend (`clipBbox` on the model, `validate_clip_bbox`, downloader
   route, mosaic clip) — additive.
2. Deploy UI (catalog panel).

### Backward

- Fully reversible. Reverting the backend leaves `clipBbox` ignored (unknown
  field on the document is harmless); imagery is produced unclipped. No blob
  cleanup required.

## Data Volume Estimates

| Entity | Size | Notes |
|---|---|---|
| `clipBbox` field | ~64 bytes | per ImageLayer |
| Clipped artifacts | **smaller** than unclipped | clip reduces mosaic/COG size |

## Caching Strategy

| Data | Cache Layer | TTL | Invalidation |
|---|---|---|---|
| STAC catalogs | Browser (per panel open) | session | Re-fetched on event change |
| TiTiler tiles | Browser tile cache | default | — |
