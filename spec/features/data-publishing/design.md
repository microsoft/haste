# Technical Design: Data Publishing & Published Datasets

## Overview

A **Publish dataset** action on model results opens a Fluent UI dialog
(name / description / target). Submitting calls `PutPublishDatasetQueueMessage`,
which writes a `PublishedDataset` record (status `PENDING`) to the metadata
store and enqueues a message on `publish-queue`. A queue worker resolves a
`PublishingProvider` from a registry and runs it: **Local** copies artifacts
into an immutable published prefix and records retrieval links; **Planetary
Computer** builds STAC and ingests it into a MPC Pro GeoCatalog. Status flows
`PENDING → IN_PROGRESS → PUBLISHED | FAILED`. A new catalog-style
**Published Datasets** section (modeled on `ModelCatalog.jsx`) lists the
records. The provider abstraction is the extension seam: new targets are new
`PublishingProvider` subclasses + a registry entry, with no UI/API/queue change.

Reference: HASTE architecture in `docs/architecture.md`; STAC precedent in the
[open-data-catalog](../open-data-catalog/) spec.

## Architecture

### Component Diagram

```
┌───────────────────────────┐  PutPublishDatasetQueueMessage   ┌────────────────────┐
│  React UI                 │─────────────────────────────────▶│  hastefuncapi       │
│  ModelResultsButton →     │                                   │  - validate input   │
│  PublishDatasetModal      │◀── GetPublishingProviders ────────│  - write record     │
│  PublishedDatasets page   │◀── GetPublishedDatasets ──────────│  - enqueue          │
└───────────────────────────┘                                   └─────────┬──────────┘
                                                                queue msg  │ (publish-queue)
                                                                           ▼
                              ┌────────────────────────────────────────────────────┐
                              │  hastefuncqueues: GetPublishDatasetQueueMessage      │
                              │  PublishingProcessor.run(dataset)                    │
                              │      registry.resolve(target) → PublishingProvider   │
                              └───────┬───────────────────────────────┬─────────────┘
                                      │ Local                          │ Planetary Computer
                          ┌───────────▼──────────┐        ┌────────────▼─────────────────┐
                          │ LocalHasteStorage     │        │ PlanetaryComputerProvider     │
                          │ Provider              │        │  stac.py (pystac+geopandas)   │
                          │  copy → published/    │        │  POST /stac/collections       │
                          │  {datasetId}/         │        │  POST /stac/.../items         │
                          └───────────┬──────────┘        │  poll ingestion `location`    │
                                      │                    └────────────┬─────────────────┘
                          ┌───────────▼──────────┐        ┌─────────────▼────────────────┐
                          │ Blob / Data Lake      │        │ MPC Pro GeoCatalog            │
                          │ (HASTE artifacts)     │◀───────│ copies assets via ingestion   │
                          └───────────────────────┘  SAS  │ source (SAS / managed id)     │
                                      ▲                    └───────────────────────────────┘
                                      │ update status/links
                          ┌───────────┴──────────┐
                          │ PUBLISHED_DATASETS    │  metadata (Cosmos/Blob) — single `index` doc
                          │ MetadataProcessor     │
                          └───────────────────────┘
```

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Publishing models | `hastelib/src/hastegeo/core/models/publishing.py` | `PublishedDataset`, `PublishRequest`, `PublishTarget`/`PublishStatus` enums, `ProviderInfo`, `PublishResult` | Python / Pydantic |
| Provider ABC | `hastelib/src/hastegeo/core/publishing/base.py` | `PublishingProvider` abstract base + `ProviderConfigField` | Python |
| Provider registry | `hastelib/src/hastegeo/core/publishing/registry.py` | Register/resolve providers by id; expose `ProviderInfo` list | Python |
| Local provider | `hastelib/src/hastegeo/core/publishing/local_provider.py` | Copy/register artifacts in HASTE storage; return links | Python |
| GeoCatalog client + auth | `hastelib/src/hastegeo/core/publishing/geocatalog_client.py` | Hardened REST wrapper (collections/items/ingestion/SAS) + Entra token cache; no redirects, explicit timeouts, status-only errors | Python / requests / azure-identity |
| PC transport adapter | `hastelib/src/hastegeo/core/publishing/planetary_computer_transport.py` | Turns the async `202` + operation-location flow into resumable steps; SSRF origin-pinning, failed-item accounting | Python |
| PC provider | `hastelib/src/hastegeo/core/publishing/planetary_computer_provider.py` | Orchestrate: ensure collection, build+ingest items, poll, validate, links | Python / azure-identity |
| STAC builder | `hastelib/src/hastegeo/core/publishing/stac.py` | Build STAC Collection + vector Items (geometry from valid-area mask) from a HASTE `ArtifactBundle` + `assessmentSummary` | Python / pystac / geopandas / shapely |
| Publishing processor | `hastelib/src/hastegeo/core/processors/publishing.py` | Orchestrate validate → persist → enqueue → run → status | Python |
| Published Datasets page | `ui/src/Components/PublishedDatasets.jsx` | Catalog-style list (search/sort/paginate/states) | React / Fluent UI |
| Dataset row | `ui/src/Components/PublishedDatasetRow.jsx` | One dataset: metadata, status, retrieve/unpublish actions | React / Fluent UI |
| Publish dialog | `ui/src/Components/PublishDatasetModal.jsx` | Name/description/target form; prefill; submit | React / Fluent UI |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| Model results menu | `ui/src/Components/ProjectManagement/ModelResultsButton.jsx` | Add "Publish dataset…" `MenuItem` (after Assessment Report); open `PublishDatasetModal` |
| API helpers | `ui/src/util/api.js` | New calls via existing `apiGet`/`apiPost`/`apiDelete` (no new transport) |
| Assessment summary | new `ui/src/util/assessmentSummary.js` | Extract `buildSummarySentence()` from `AssessmentReportModal.jsx` for reuse as description prefill |
| Sidebar / routing | `ui/src/Components/AppSidebar.jsx`, `AppBody.jsx` | Register "Published Datasets" nav item + `/published-datasets` route |
| Config | `hastelib/src/hastegeo/core/config.py` | `MetadataTypes.PUBLISHED_DATASETS`; `publish_queue_name`; PC GeoCatalog config block |
| API module | `api/hastefuncapi/function_app.py` | 5 new thin routes (below) |
| Queue module | `api/hastefuncqueues/function_app.py` | `GetPublishDatasetQueueMessage` trigger |

## Publishing provider interface

The core abstraction. Providers are stateless, constructed with resolved config.

```python
# core/publishing/base.py
class ProviderConfigField(BaseModel):
    key: str            # e.g. "geocatalog_url"
    label: str
    required: bool
    secret: bool = False

class PublishingProvider(ABC):
    # --- metadata ---
    @property
    @abstractmethod
    def provider_id(self) -> str: ...          # "local" | "planetary_computer"
    @property
    @abstractmethod
    def display_name(self) -> str: ...          # "Local (In App storage)"
    @property
    def description(self) -> str: return ""
    @property
    def config_requirements(self) -> list[ProviderConfigField]: return []
    def is_configured(self) -> bool: return True   # False → shown disabled in UI

    # --- validation (fast, pre-enqueue) ---
    @abstractmethod
    def validate(self, req: "PublishRequest") -> Optional[str]:
        """None if publishable, else a user-facing error string."""

    # --- publish (slow, in the queue worker) ---
    @abstractmethod
    def publish(self, dataset: "PublishedDataset",
                artifacts: "ArtifactBundle") -> "PublishResult":
        """Do the work; return links/status/provider metadata."""

    # --- teardown (unpublish) ---
    def unpublish(self, dataset: "PublishedDataset") -> None:
        """Best-effort cleanup; default no-op."""
```

`ProviderInfo` (returned to the UI by `GetPublishingProviders`) is the
serializable projection of a provider's metadata + `is_configured()`.
`ArtifactBundle` resolves a model's publishable artifacts (gpkg, valid mask,
processed COGs, footprints, assessment-report JSON) to `{kind, blob_path,
media_type, sas_url}` entries, built from the `Model`/`ImageLayer` documents. It
exposes which kinds are **available** (so the dialog can render only real
outputs) and is **filtered to the user-selected `artifacts`** before a provider
runs — providers publish exactly the selected subset, never more.

### Registry

```python
# core/publishing/registry.py
_REGISTRY: dict[str, PublishingProvider] = {}
def register(p: PublishingProvider): _REGISTRY[p.provider_id] = p
def resolve(provider_id: str) -> PublishingProvider: ...
def list_infos() -> list[ProviderInfo]: ...     # for GetPublishingProviders
# Local + PlanetaryComputer registered at import time.
```

Adding a provider = implement `PublishingProvider`, call `register(...)`. No
other layer changes. This satisfies the extensibility success criterion.

### Internal interfaces (hastegeo)

| Module | Function/Class | Signature | Description |
|---|---|---|---|
| `core/models/publishing.py` | `PublishedDataset` | Pydantic model | Persisted record (see [data-model.md](data-model.md)) |
| `core/publishing/base.py` | `PublishingProvider` | ABC | Provider contract above |
| `core/publishing/registry.py` | `resolve`, `list_infos` | `(id)->provider`, `()->[ProviderInfo]` | Registry access |
| `core/publishing/local_provider.py` | `LocalHasteStorageProvider.publish` | `(dataset, bundle)->PublishResult` | Copy + link |
| `core/publishing/planetary_computer_provider.py` | `PlanetaryComputerProvider.publish` | `(dataset, bundle)->PublishResult` | STAC ingest + poll |
| `core/publishing/stac.py` | `build_collection`, `build_raster_item`, `build_vector_item` | see [STAC mapping](#stac-mapping) | STAC construction |
| `core/processors/publishing.py` | `PublishingProcessor.enqueue` / `.run` | `(request)->PublishedDataset` / `(dataset)->None` | Orchestration |

## API Design

### hastefuncapi endpoints

Per `AGENTS.md`, these are thin wrappers in `function_app.py` delegating to
`PublishingProcessor` / registry in `hastegeo`.

#### `GET /api/GetPublishingProviders`

**Auth:** `func.AuthLevel.FUNCTION`. Returns providers for the dialog dropdown.

**Response (200):**
```json
{
  "providers": [
    { "id": "local", "displayName": "Local (In App storage)",
      "description": "string", "isConfigured": true, "supportsAsync": true,
      "configRequirements": [] },
    { "id": "planetary_computer", "displayName": "Planetary Computer",
      "isConfigured": false,
      "configRequirements": [
        { "key": "geocatalog_url", "label": "GeoCatalog URL", "required": true, "secret": false }
      ] }
  ]
}
```

#### `GET /api/GetPublishedDatasets`

**Auth:** `func.AuthLevel.FUNCTION`. Optional `projectId` (GUID) filter.

**Response (200):** `{ "publishedDatasets": [PublishedDataset, ...] }` sorted by
`publishedDate` desc (mirrors `GetModelCatalog`).

#### `GET /api/GetPublishedDataset`

**Auth:** `func.AuthLevel.FUNCTION`. Params: `datasetId` (required).
**Response (200):** `{ "publishedDataset": PublishedDataset }`; **404** if absent.

#### `POST /api/PutPublishDatasetQueueMessage`

**Auth:** `func.AuthLevel.FUNCTION`. Starts a publish job (name follows the
existing `PutRunModelQueueMessage` / `PutArtifactsZipQueueMessage` convention).

**Request:**
```json
{
  "projectId": "guid — required",
  "imageLayerId": "string — required",
  "modelId": "string — required (source of artifacts)",
  "name": "string — required, user-edited, prefilled '<project> – <layer>'",
  "description": "string — optional, prefilled from assessment report",
  "target": "local | planetary_computer — required",
  "artifacts": "string[] — required, ≥1; subset of the model's available kinds (gpkg | valid_mask | footprints | processed_cog | …). Defaults to all available if omitted.",
  "providerConfig": "object — optional per-provider overrides (e.g. collectionId)"
}
```

**Behavior:** validate params → build `ArtifactBundle` and confirm every
requested kind is actually available (**400/404** otherwise) → resolve provider →
`provider.validate(req)` (400 on error) → create `PublishedDataset`
(`status=PENDING`, new `datasetId`, `artifacts`=selected, `publishedByUser` from
client principal) → upsert into the `index` doc → enqueue `{datasetId, projectId}`
on `publish-queue` → **202** with the record.

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Missing/invalid params, unknown target, empty `artifacts`, or `provider.validate` rejected |
| 401 | Missing/invalid function key or MSAL token |
| 404 | Project / layer / model not found, or a requested artifact kind is not available on the model |
| 409 | A dataset with the same name for this project/layer/target already publishing |
| 500 | Metadata write / enqueue failure |

#### `DELETE /api/DeletePublishedDataset`

**Auth:** `func.AuthLevel.FUNCTION`. Params: `datasetId` (required). Permission:
publisher or admin (client principal). Calls `provider.unpublish(dataset)`
(best-effort), removes the record. **Response (200):** `{ "deletedDataset": {...} }`.

Existing `GET /api/GetAssessmentReport` (function_app.py:4045) is **reused**
unchanged for the description prefill — no new endpoint.

### Queue message (hastefuncqueues)

#### Queue: `publish-queue` (`PUBLISH_QUEUE_NAME`, default `publish-queue`)

**Message Schema:**
```json
{ "datasetId": "string", "projectId": "string" }
```

**Trigger behavior (`GetPublishDatasetQueueMessage`):**
1. Load `PublishedDataset` from the `index` doc; set `status=IN_PROGRESS`,
   append status message, persist.
2. Build `ArtifactBundle` from the model/layer documents.
3. `provider = registry.resolve(dataset.target)`; `result = provider.publish(...)`.
4. On success: merge `result.links` / `result.providerMetadata`,
   `status=PUBLISHED`, `publishedDate=now`; persist.
5. On exception: `status=FAILED`, `statusMessage=<error>`; persist; log. Message
   visibility follows the existing immediate-processing convention
   (`visibility_timeout=0`).

## Behavior & Logic

### Core flow (publish)

1. Analyst opens a completed model's results → **Publish dataset…**.
2. Dialog loads: name prefilled `${project} – ${layer}`; description prefilled
   from `GetAssessmentReport`; **asset checklist populated from the model's
   available outputs (all prechecked)**; targets from `GetPublishingProviders`.
3. Analyst optionally trims the asset selection, then Submit →
   `PutPublishDatasetQueueMessage` validates (incl. ≥1 available asset) + writes
   `PENDING` record (with selected `artifacts`) + enqueues; dialog confirms and
   closes.
4. Worker runs the provider; status → `IN_PROGRESS` → `PUBLISHED`/`FAILED`.
5. Published Datasets section lists the record; UI polls while `IN_PROGRESS`.

### Local provider

- Iterate the `ArtifactBundle` (already filtered to the **selected** kinds); for
  each selected artifact, **copy** the blob to
  `published/{hash(projectId)}/{datasetId}/{artifact_name}` (same container as
  existing artifacts) using the artifact-storage layer; generate a fresh SAS URL.
- `PublishResult.links = { "<kind>": "<sas_url>", ... }`; also store the
  assessment-report JSON snapshot for provenance.
- `unpublish`: delete the `published/{datasetId}/` prefix.
- Always **copies** into the immutable published prefix (lifecycle
  independence); total copied bytes are bounded by `PUBLISH_MAX_TOTAL_BYTES`.

### Planetary Computer provider — STAC mapping

The PC provider builds STAC and ingests it into a Planetary Computer Pro
GeoCatalog over a small, hardened REST client (`geocatalog_client.py`) plus a
resumable transport adapter. The client and STAC builder are HASTE-owned and
transport-agnostic (no `azure-planetarycomputer` SDK dependency), so the
ingestion flow is fully unit-testable against HTTP fixtures.

Libraries: `azure-identity`, `pystac[validation]`, `geopandas`, `pyogrio`,
`shapely`, `requests`. The damage products are vector, so item geometry is built
from the valid-area mask (`geopandas`/`shapely`), not from a COG — `rio-stac` is
not used in v1 (it would return only if/when rasterized COGs are published; see
the render limitation below). Auth:
`DefaultAzureCredential().get_token("https://geocatalog.spatio.azure.com/.default")`,
token cached with a ~300 s expiry skew; Bearer header; **all** calls carry
`?api-version=2026-04-15`. Redirects are never followed and every request carries
explicit (connect, read) timeouts; errors carry only the HTTP status, never the
response body (which may contain tokens/SAS).

**GeoCatalog REST surface:**

| Op | Method + path | Notes |
|---|---|---|
| Ensure collection | `GET /stac/collections/{id}` → 404 ⇒ `POST /stac/collections` else `PUT /stac/collections/{id}` | upsert |
| Ingest item | `POST /stac/collections/{id}/items` | 202 + `location` → poll |
| Replace item | `DELETE …/items/{itemId}` then re-POST | idempotent re-publish |
| Search / verify | `POST /stac/search` `{collections:[id]}` | post-publish validation |
| Configure | `PUT …/configurations/tile-settings`, `POST …/render-options`, `POST …/mosaics` | display config |
| Collection asset | `POST /stac/collections/{id}/assets` (multipart) | thumbnail |
| Sign published asset | `GET /sas/sign?href=<assetHref>` → signed asset URL | **assets live in SAS-protected managed storage** |
| Ingestion source | `GET/POST/DELETE /inma/ingestion-sources` | see below |

**Collection (per event ≈ per project):** ensure it exists via the upsert above.
Built as a STAC `Collection` with `id`, `title`, `description`, `license`,
`keywords`, `providers`, `extent` (spatial bbox + temporal interval computed from
items), `summaries`, `item_assets` (declares `buildings` GPKG + `aoi` GeoJSON),
`links`, and `stac_extensions: [item-assets/v1.0.0]`. Scope is **one collection
per event**; a HASTE project maps to one event → `id` derived from the project
(slugified to GeoCatalog id rules — no `-_+().`), e.g. `haste-<projectSlug>`.

**Item (per response ≈ per published dataset/layer):** one STAC Item per
assessment response.
- **Geometry = the valid-area mask polygon** (the region actually assessed),
  read via `geopandas`, unioned, reprojected to EPSG:4326; `bbox` and
  `haste:aoi_area_km2` computed from it (better than a raster footprint for damage
  products).
- **Assets:** `buildings` — damage GeoPackage (`application/geopackage+sqlite3`,
  roles `[data]`, `proj:code` of the source CRS); `aoi` — valid mask GeoJSON
  (`application/geo+json`, roles `[metadata]`). Only the analyst-**selected**
  artifacts become assets.
- **Properties:** `title`, `description`, `datetime`, `license`, `proj:code`, and
  HASTE stats under the tool-neutral `haste:` prefix (`buildings_total`,
  `buildings_cloud`, `buildings_clear`, `buildings_damaged`,
  `damaged_pct_of_clear`), plus `…validation_*` (precision/recall/extrapolated)
  from the assessment report and `…merge_*` for merged products — sourced from
  `assessmentSummary`. The prefix is a single constant (`PROPERTY_PREFIX` in
  `stac.py`) so it can be changed in one place.
- **Providers:** a STAC `providers` list layers attribution — the imagery
  source(s) as `producer`/`licensor` (inferred from the image layer's
  `sourceType*` via a small canonical map, unknown types passed through,
  non-vendor placeholders like `n/a`/`rgb/no_processing`/`mercy_corps` dropped),
  and the deployment's operating organization as `processor` (from
  `PUBLISHING_ORGANIZATION_NAME`/`_URL`; omitted when unset). Present on the item
  (per-dataset) and unioned onto the collection. Operators can **override** the
  inferred imagery sources per dataset via the Edit-metadata form; the value is
  persisted on `PublishedDataset.imagerySources`. Editing re-emits the item
  `providers` and recomputes the collection union; unpublish likewise re-unions
  the collection from the datasets that remain (`stac.py` helpers
  `refresh_collection_after_edit` / `rebuild_collection_after_removal`).
- `stac_extensions: [projection/v2.0.0]`; `item["collection"] = collection_id`;
  **item id sanitized** to the GeoCatalog charset (no `-_+().`).

**Ingest:** `POST …/items` (Item or ItemCollection) → **202** + `location`; poll
`location` (falls back to `/inma/operations/{id}`) until a terminal status
(`Succeeded`/`Finished`/`Failed`/`Cancelled`/`Completed`), and also check
`additionalInformation.TotalFailedItems` for partial failures. **The GeoCatalog
copies each asset from its HASTE blob href into its own managed storage and
rewrites the href** — so published assets are served from PC storage, not HASTE.
- **Public source containers** need no ingestion source.
- **Private source containers** must be registered first as a **`SasToken`**
  ingestion source (`POST /inma/ingestion-sources` with `{kind:"SasToken",
  connectionInfo:{containerUrl, sasToken}}`) — `SasToken` is the **only kind the
  API accepts**; managed-identity sources are **portal/ARM-only** (grant the
  catalog's user-assigned identity *Storage Blob Data Reader* on the HASTE storage
  account).

**Post-publish validation:** search the collection, confirm each item + required
assets exist, compare item geometry to the source mask, and Range-GET each asset
href (signed via `/sas/sign`) for reachability.

`PublishResult.links = { "stac_collection": ".../stac/collections/{id}",
"explorer": "<geocatalog_explorer_url>" }`;
`providerMetadata = { "collectionId": ..., "itemIds": [...], "apiVersion": ...,
"assetsCopiedToManagedStorage": true }`.

`unpublish`: `DELETE /stac/collections/{id}/items/{itemId}` per item (best-effort;
collection retained if it still holds other datasets for the project).

> **Render limitation (important).** Planetary Computer Pro cloud-optimizes and
> renders **raster** data only; **GeoPackage/GeoJSON are stored and served for
> download through the STAC API but are NOT tiled and NOT shown on the Explorer
> map.** So a PC-published damage dataset appears in the Explorer as **item
> footprints + metadata**, and consumers **download** the GeoPackage. Rendering
> damage *on the map* would require rasterizing predictions to COGs and adding
> render options — **out of scope for v1** (a future `processed_cog`/raster asset
> path can use `rio-stac`). The UX must set this expectation (see
> [ux-spec.md](ux-spec.md)); do not promise map rendering of the damage layer.

#### Provider implementation notes

The provider runs the ingestion as a **bounded-step state machine** so no single
queue invocation blocks on a long-running ingestion:

- **Ensure collection:** `GET` the collection; on 404 create it. Collection
  creation is **synchronous** (`201`); item ingestion is **asynchronous** (`202`
  + `operation-location`).
- **Ingest item:** `POST …/items` → `202`; persist the returned operation URL as
  a continuation token (origin-pinned to the GeoCatalog to prevent SSRF).
- **Poll:** each subsequent step polls the operation URL until a terminal status.
  Terminal success states include `Succeeded`, `Finished`, `Completed`; also check
  `additionalInformation.totalFailedItems` and fail on partial failures. Poll
  attempts are bounded by config (`PC_VERIFY_ATTEMPTS`) so a stuck ingestion
  eventually FAILs rather than looping forever.
- **Unpublish:** `DELETE …/items/{itemId}` per item; retain the collection while
  it still holds other datasets for the project.

### Edge Cases

| Case | Expected Behavior |
|---|---|
| Model has no `gpkgUrl` / no publishable artifact | Publish action disabled (UI) + 404 (API) |
| User selects zero assets | Publish disabled (UI) + 400 (API) |
| Requested artifact kind not produced by the model | Grayed/omitted in the dialog; 404 if forced via API |
| Some selected assets missing at publish time (deleted/re-run) | Publish what remains; note skipped kinds in `statusMessage` |
| Assessment report unavailable | Description prefill left blank; publish still allowed |
| Duplicate dataset name (same project/layer/target, still publishing) | 409; UI shows "already publishing" |
| PC provider not configured | Target shown disabled; `validate` returns error if forced |
| GeoCatalog 40x on an item | Job → FAILED with the API error text; no partial links surfaced |
| Ingestion poll never terminates | Bounded poll (timeout) → FAILED "ingestion timed out"; safe to retry |
| Source model deleted after publish (Local, copy mode) | Links still resolve (immutable published copy) |
| Collection id collision across projects | Id is project-slug scoped; 409 → reuse via PUT |
| GeoCatalog item-id illegal chars | Sanitized before POST |

### Error Handling

| Error Condition | Response | Recovery |
|---|---|---|
| Blob copy timeout (Local) | status FAILED + message | Re-publish (idempotent on `datasetId`) |
| GeoCatalog auth failure | status FAILED "auth" | Fix credential/ingestion source; re-publish |
| GeoCatalog 409 collection exists | Treat as success (reuse) | PUT to update metadata |
| Ingestion partial failure (`TotalFailedItems>0`) | status FAILED + per-item detail | Replace-and-repost failed items |
| Private HASTE container, no ingestion source | Ingestion can't read assets → FAILED | Register `SasToken` source (or grant MI reader) then re-publish |
| Queue message poison | Standard Azure Queue retry → dead-letter | Admin inspects; status stays IN_PROGRESS until re-run |

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `PUBLISHING_ENABLED` | bool | `false` | App Settings | Master feature flag (section + Publish action) |
| `PUBLISH_QUEUE_NAME` | str | `publish-queue` | `config.py` / App Settings / `docker-compose.yml` | Publish job queue (auto-created at runtime) |
| `PC_PROVIDER_ENABLED` | bool | `false` | App Settings | Register/expose the Planetary Computer provider |
| `PC_GEOCATALOG_URL` | url | (unset) | App Settings | MPC Pro GeoCatalog base URL (no trailing `/`) |
| `PC_EXPLORER_URL` | url | (unset) | App Settings | Explorer base URL for published-dataset links |
| `PC_INGESTION_SOURCE` | str | (unset) | App Settings | Only for **private** HASTE containers (`SasToken` source); public need none |
| `PC_COLLECTION_PREFIX` | str | `haste-` | App Settings | Collection id prefix (one collection per project/event) |
| `PUBLISH_MAX_TOTAL_BYTES` | int | 5 GiB | App Settings (override) | Max total published bytes per dataset |
| `PUBLISHED_DOWNLOAD_SAS_MINUTES` | int | `15` | App Settings (override) | Local retrieval SAS TTL |
| `PUBLISHING_LOCK_CONTAINER` | str | `publishing-locks` | App Settings (override) | Blob-lease container (auto-created at runtime) |
| `PC_VERIFY_ATTEMPTS` | int | code default | App Settings (override) | Ingestion poll attempt bound |
| `VITE_*` | — | — | `ui/.env.*` | None new; UI uses existing `api.js` transport |

The STAC `api-version` (`2026-04-15`) and the Entra token scope
(`https://geocatalog.spatio.azure.com/.default`) are **code constants** in the
GeoCatalog client, not App Settings. For the deploy-time `azd` env var → App
Setting mapping and the enablement steps, see
[rollout.md](rollout.md#operator-configuration-app-settings).

Credentials use **managed identity** (`DefaultAzureCredential`) in Azure and
`AzureCliCredential`/env locally — no secrets in code (per
`docs/security-configuration.md`).

**Provider configuration is operator-owned (v1).** The keys above are Azure
Function App Settings set at deploy time by an admin/operator, plus a
pre-registered GeoCatalog ingestion source; there is **no in-app admin screen**
for configuring providers in v1. The app never stores provider credentials
(managed identity only) and never accepts them from the UI. The Publish dialog
only *reflects* the resulting state — `GetPublishingProviders` reports
`isConfigured` (and `configRequirements` purely to explain *why* a provider is
disabled). A self-service admin UI is a possible future addition behind the same
`ProviderInfo` contract (no UI/API rework needed) — see
[user-stories.md](user-stories.md#out-of-scope).

## Observability

- **UI:** per-row status chips; dialog error banner from `provider.validate`.
- **Backend:** structured logging in `PublishingProcessor` and each provider
  (`Publishing dataset {id} via {provider} …`, `Ingestion status: {status}`);
  `statusMessage` on the record surfaces failures (mirrors `Model.statusMessage`).
- **Queue depth:** `publish-queue` monitored like other queues.

## Open Questions

- [ ] Collection granularity: one STAC Collection **per project** (default) vs
      per event vs per dataset — start per-project, revisit.
- [ ] Should Local publishing register a lightweight **self-hosted STAC** record
      too (so both providers are STAC-shaped)? Interface allows it.
- [ ] Hard backend RBAC for unpublish vs UI-gated (v1 checks client principal in
      the API) — align with existing admin checks.
- [ ] Retention/GC of `published/{datasetId}/` copies when a project is deleted.
