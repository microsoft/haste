# Data Model: Data Publishing & Published Datasets

> HASTE's local/dev stack stores metadata as JSON in Blob Storage
> (`METADATA_STORAGE_TYPE=blob`) and, in cloud, in Cosmos DB, both behind
> `MetadataProcessor`. The "Cosmos" sections below describe the logical
> documents; they apply equally to the blob-backed metadata store. The design
> mirrors the **Model Catalog**, which stores a single `index` document under the
> `MODEL_CATALOG` metadata type (`function_app.py:2942`).

## Cosmos DB Changes

### New metadata type / logical container

| Container (metadata type) | Partition Key | Description |
|---|---|---|
| `PUBLISHED_DATASETS` | none (global `index`, like `MODEL_CATALOG`) | Single document `{"publishedDatasets": [PublishedDataset, ...]}` |

New enum member `MetadataTypes.PUBLISHED_DATASETS` in `config.py`
(`get_metadata_types()`), loaded/saved via
`MetadataProcessor(data_type=...).load("index")` — the exact pattern
`GetModelCatalog` uses.

### Modified Containers

| Container | Change | Migration Needed? |
|---|---|---|
| (none) | Existing `Model`/`ImageLayer`/`Project` documents are **read-only** inputs to publishing | no |

### New Document Schema

**Container:** `PUBLISHED_DATASETS` · **Document id:** `index` (single) holding
an array of `PublishedDataset`:

```jsonc
// PublishedDataset (one array element)
{
  "datasetId": "uuid",                 // primary key within the array
  "name": "Hurricane Harvey – Layer 1",// user-edited, prefilled '<project> – <layer>'
  "description": "string",             // prefilled from assessment report summary
  "interactiveViewerUrl": "https://… | null", // optional, editable; PC rel=preview link
  "imagerySources": ["Vantor"],        // provider attribution; inferred from source type (not editable)
  "sourceImageryReferences": [         // source-scene provenance (open-data only)
    { "programId": "vantor-open-data", "href": "https://…/scene.json",
      "title": "…", "license": "CC-BY-NC-4.0", "attributable": true,
      "sourceUrl": "https://…/scene.tif | null" } // COG the ref was captured from; UI correlation only, never emitted to STAC
  ],
  "sourceImageryCitation": "https://… | text | null", // optional, editable, URL-aware
  "projectId": "uuid",
  "imageLayerId": "string",
  "modelId": "string",                 // source model whose artifacts were published
  "target": "local | planetary_computer",
  "status": "PENDING | IN_PROGRESS | PUBLISHED | FAILED",
  "statusMessage": "string",           // appended log, like Model.statusMessage
  "publishedByUser": "user@contoso.com",
  "createdDate": "ISO 8601",
  "publishedDate": "ISO 8601 | null",  // set when status → PUBLISHED
  "artifacts": [                       // user-selected subset that was published
    { "kind": "gpkg", "mediaType": "application/geopackage+sqlite3", "blobPath": "…", "sizeBytes": 12345 },
    { "kind": "valid_mask", "mediaType": "application/geo+json", "blobPath": "…" },
    { "kind": "processed_cog", "mediaType": "image/tiff; application=geotiff", "blobPath": "…" }
  ],
  "links": {                           // provider output (retrieval)
    "gpkg": "https://…sas",            // Local
    "stac_collection": "https://…/stac/collections/haste-…",  // PC
    "explorer": "https://…"            // PC
  },
  "providerMetadata": {                // provider-specific, opaque to UI
    "collectionId": "haste-…", "itemIds": ["…"], "apiVersion": "2026-04-15"
  },
  "assessmentSummary": {               // snapshot for provenance + STAC properties
    "predictedDamaged": 1234, "precision": 0.82, "recall": 0.77
  }
}
```

**RU / cost:** the `index` document grows by ~1–2 KB per dataset; a single upsert
per publish/status transition — negligible, same profile as the model catalog.

### Modified Document Schema

| Container | Field | Before | After | Notes |
|---|---|---|---|---|
| (none) | — | — | — | No changes to existing documents; publishing only reads them |

---

## Blob Storage Changes

### New path prefix (no new container)

| Container | Access Level | Naming Convention | Content Type |
|---|---|---|---|
| existing artifacts/data container | private | `published/{datasetId}/{artifact_name}` | GPKG / GeoTIFF / GeoJSON / JSON |

The Local provider copies the source model's artifacts into an **immutable
published prefix** so the dataset survives re-run/deletion of the source model.
The prefix is kept to three in-container segments (`published/{datasetId}/{file}`)
so the UI can serve downloads through the existing managed-identity storage proxy
(`get-artifacts`), which the VNet-only storage account requires — a direct blob
SAS from the browser is denied by the storage firewall. `{datasetId}` is a UUID,
so no project-hash prefix is needed for uniqueness.

### Blob Path Conventions

```
{container}/
  published/
    {datasetId}/
      predicted_damage_{modelName}.gpkg
      valid_area_mask_{projectId}_{layerId}.geojson
      processed_imagery_post_event_cog_{projectId}_{layerId}.tif
      building_footprints_{projectId}_{layerId}.gpkg
      assessment_report_{datasetId}.json    # snapshot for provenance
```

Names reuse the existing artifact templates (`config.py:69-141`); the `published/`
segment and `{datasetId}` are the only new path elements.

### Modified Containers

| Container | Change | Description |
|---|---|---|
| (none) | additive prefix only | Existing artifact paths untouched |

---

## Data Lake Changes

None. Large COGs already live in the artifact/data store; the published prefix is
in the same store. No new filesystem.

---

## Queue Storage Changes

### New Queues

| Queue Name | Message Schema | Producer | Consumer |
|---|---|---|---|
| `publish-queue` | `{ "datasetId": "…", "projectId": "…" }` | `hastefuncapi` (`PutPublishDatasetQueueMessage`) | `hastefuncqueues` (`GetPublishDatasetQueueMessage`) |

Registered in `config.get_queue_config()` as `publish_queue_name`
(default `publish-queue`), alongside the existing `train`/`inference`/`zip`
queues. Azurite seeds it in the dev stack.

---

## Azure Batch Changes

None. Publishing is I/O-bound (blob copy, STAC HTTP calls) and runs in the
Functions queue worker — no GPU/Batch pool. (If future providers need heavy
raster reprocessing, the provider can enqueue Batch work, but v1 does not.)

---

## STAC mapping (Planetary Computer target)

Logical mapping from HASTE artifacts to STAC (see
[design.md](design.md#stac-mapping)):

| HASTE artifact | STAC representation | Key fields |
|---|---|---|
| Valid-area mask GeoJSON | **Item geometry** (+ `aoi` asset) | union polygon → EPSG:4326 `geometry`/`bbox`; `haste:aoi_area_km2` computed; asset `application/geo+json`, roles `[metadata]` |
| Damage GPKG (`predicted_damage_*`) | `buildings` asset on the Item | `application/geopackage+sqlite3`, roles `[data]`, `proj:code` of source CRS |
| Building footprints GPKG | `buildings` GPKG already carries footprints (or its own asset) | `application/geopackage+sqlite3` |
| Assessment report | Item `properties` (`haste:buildings_total/cloud/clear/damaged`, `…validation_*`) | from `assessmentSummary` |
| Imagery source type(s) | STAC `providers` (`licensor`) | inferred from image layer `sourceType*`; canonical map + passthrough; unioned onto the collection |
| Deployment organization | STAC `providers` (`producer` + `processor`) | `PUBLISHING_ORGANIZATION_NAME`/`_URL`; omitted when unset |
| Project (≈ event) | STAC Collection | `id=haste-<projectSlug>`, `extent`, `providers`, `keywords`, `summaries`, `item_assets`, `stac_extensions:[item-assets/v1.0.0]` |
| Item | `stac_extensions:[projection/v2.0.0]`, `collection=<id>` | id sanitized (no `-_+().`) |

- **Item geometry is the valid-area mask**, not a raster footprint — the region
  actually assessed. `rio-stac`/raster items are only introduced if/when a
  rasterized COG is published for map rendering (out of scope v1).
- **Vector assets (GPKG/GeoJSON) are download-only** in PC Pro — stored and
  served via the STAC API but **not tiled / not rendered** in the Explorer (see
  [design.md render limitation](design.md#planetary-computer-provider--stac-mapping)).
- On ingest, the GeoCatalog **copies assets into its own managed storage and
  rewrites hrefs**; reading them needs a collection SAS token
  (`GET /sas/token/{collectionId}`).

---

## Data Flow

### Write path

```
UI → PutPublishDatasetQueueMessage (validate + provider.validate)
        → PUBLISHED_DATASETS index doc (PENDING)
        → publish-queue (datasetId)
   hastefuncqueues → PublishingProcessor.run → provider.publish
        Local: copy → published/{datasetId}/… ; links=SAS (served via storage proxy)
        PC:    pystac/geopandas → POST /stac/collections(/items) → poll operations
        → PUBLISHED_DATASETS index doc (PUBLISHED | FAILED, links, providerMetadata)
```

### Read path

```
UI → GetPublishedDatasets → PUBLISHED_DATASETS index doc (list)
UI → GetPublishedDataset  → single record (+ links)
UI → Local artifact SAS URL (direct download)  |  PC explorer/collection link (external)
```

## Migration Plan

### Forward

1. Add `PUBLISHED_DATASETS` metadata type + `publish_queue_name` (additive).
2. Deploy `hastelib` publishing package + `hastefuncqueues` trigger.
3. Deploy `hastefuncapi` routes.
4. Deploy UI section + dialog.

No backfill: the `index` document is created lazily on first publish (like the
model catalog's `FileNotFoundError → empty catalog`).

### Backward

- Fully reversible. Reverting API/UI hides the feature; the `PUBLISHED_DATASETS`
  document and `published/` blobs are inert (unknown metadata type / extra blob
  prefix are harmless). Optional cleanup: delete the `index` doc and
  `published/*` prefixes. PC collections/items, if created, persist in the
  GeoCatalog until deleted via its API (out-of-band).

## Data Volume Estimates

| Entity / Container | Initial Size | Growth Rate | Retention |
|---|---|---|---|
| `PUBLISHED_DATASETS` index doc | ~1 KB | ~1–2 KB per dataset | life of project |
| `published/{datasetId}/` copies | = source artifacts (MB–GB) | per published dataset | until unpublish/project delete |
| `publish-queue` messages | tiny | transient | consumed immediately |

## Caching Strategy

| Data | Cache Layer | TTL | Invalidation |
|---|---|---|---|
| Published dataset list | Browser (per section open) | session | Re-fetch on publish/poll |
| Provider list | Browser | session | Re-fetch on dialog open |
| Local artifact SAS URLs | none (short-lived SAS) | SAS expiry | Re-issued on `GetPublishedDataset` |
