# Impact Analysis: Data Publishing & Published Datasets

## Scope of Change

### HASTE Components Affected

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core models | `hastelib/src/hastegeo/core/models/publishing.py` | new | low |
| Publishing package | `hastelib/src/hastegeo/core/publishing/` | new | medium |
| Publishing processor | `hastelib/src/hastegeo/core/processors/publishing.py` | new | medium |
| Config | `hastelib/src/hastegeo/core/config.py` | modified (enum, queue, PC block) | low |
| REST API | `api/hastefuncapi/function_app.py` | new (5 routes) | low |
| Queue workers | `api/hastefuncqueues/function_app.py` | new (1 trigger) | medium |
| React UI | `ui/src/Components/PublishedDatasets*.jsx`, `PublishDatasetModal.jsx`, `ModelResultsButton.jsx`, `AppSidebar.jsx`, `AppBody.jsx` | new + modified | medium |
| Docker config | `docker/docker-compose.yml`, Azurite seed | modified | low |
| CI/CD | `.github/workflows/*` (Component Governance) | modified | low |

> Existing `Model`/`ImageLayer`/`Project` documents and their endpoints are
> **read-only** inputs — no changes, so no regression surface there.

## Azure Service Impact

| Service | Change | New Cost Impact |
|---|---|---|
| Cosmos DB | New logical type `PUBLISHED_DATASETS` (single `index` doc, like model catalog) | negligible |
| Blob Storage | New `published/{datasetId}/` prefix in the existing container (copy-on-publish) | storage ∝ published artifact size (duplicates source until unpublish) |
| Queue Storage | New `publish-queue` | negligible |
| Azure Functions | +5 HTTP routes, +1 queue trigger | low consumption |
| Static Web Apps | New `/published-datasets` route + `/api/*` proxy entries | none material |
| **Planetary Computer Pro** | New external dependency (GeoCatalog + ingestion source) | **GeoCatalog resource + ingest/storage costs** (PC target only) |
| Managed Identity | GeoCatalog + storage access for the queue worker | none |

## Dependency Analysis

### Upstream Dependencies (things this feature needs)

| Dependency | Type | Status | Risk if Unavailable |
|---|---|---|---|
| `hastegeo` artifact storage + metadata layer | library | available | Local publish cannot copy/register |
| Completed model with artifacts (`gpkgUrl`, masks, COGs) | data | per-project | Nothing publishable → action disabled |
| `GetAssessmentReport` endpoint | API | available (`function_app.py:4045`) | Description prefill blank (non-blocking) |
| `azure-identity`, `pystac`, `geopandas`, `pyogrio`, `shapely` | pip | to add | PC provider unbuildable; Local unaffected |
| MPC Pro GeoCatalog + ingestion source | infra/external | to provision | PC target disabled; Local unaffected |
| Managed identity / `DefaultAzureCredential` | auth | available | PC ingestion auth fails |

### Downstream Impact (things affected by this feature)

| Consumer | How Affected | Breaking? | Migration Needed? |
|---|---|---|---|
| `hastefuncapi` callers | New endpoints only; existing untouched | no | no |
| React UI | New section + one added menu item | no | no |
| Docker Compose stack | +1 queue seed | no | no |
| Existing Cosmos documents | None read-modified | no | no |
| Model deletion flow | Local copy mode makes published data survive model deletion (intended) | no | no |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| PC GeoCatalog API/version drift (`api-version=2026-04-15`) | medium | medium | Version pinned in config; provider isolates all HTTP; contract tests against mock | `gis` |
| Ingestion source misconfig → GeoCatalog can't read HASTE blobs | medium | medium | `validate()` pre-checks config; clear FAILED `statusMessage`; runbook in rollout | `backend-dev` |
| Copy-on-publish duplicates large artifacts → storage growth | medium | low | `PUBLISH_MAX_TOTAL_BYTES` cap per dataset; GC on unpublish/project delete | `backend-dev` |
| STAC item-id / char rules rejected by GeoCatalog | medium | low | Sanitizer + `pystac.validate` before POST | `gis` |
| Long ingestion polling ties up a queue worker | low | medium | Bounded poll timeout → FAILED; idempotent re-publish | `backend-dev` |
| Credential leakage | low | high | Managed identity only; no secrets in code/logs; `security` review | `security` |
| Unpublish deletes shared PC collection | low | medium | Delete items, retain collection unless empty/owned | `gis` |

## Performance Impact

- **API latency:** `PutPublishDatasetQueueMessage` returns after a metadata
  upsert + enqueue (fast, like `PutRunModelQueueMessage`); no synchronous
  provider work. List/get mirror `GetModelCatalog` cost.
- **Queue throughput:** publish jobs are infrequent and I/O-bound; a slow PC
  poll occupies one worker for the ingestion duration — bounded by timeout.
- **Tile serving:** unaffected (`titilerfuncapi` not involved).
- **Storage I/O:** copy-on-publish reads+writes artifact-sized blobs once per
  publish.

## Security Impact

- [x] New API endpoints exposed? Yes — 5 routes at `func.AuthLevel.FUNCTION`,
      same posture as existing catalog/artifact routes; unpublish checks client
      principal.
- [x] New data classification handled? Published damage outputs (already handled
      class); no new PII. Publishing to PC **exports** data externally — gated by
      provider config + the publish action's project access.
- [x] MSAL/Entra ID auth changes? PC uses **managed identity**
      (`DefaultAzureCredential`, audience `https://geocatalog.spatio.azure.com`) —
      no new user-facing auth.
- [x] New secrets or connection strings? No secrets in code; GeoCatalog URL +
      ingestion source name are non-secret app settings; auth via managed identity.
- [ ] CORS changes in SWA? None (same-origin `/api/*`).
- [ ] New federated credentials? None beyond existing deploy OIDC.

## Compliance & Data Impact

- [x] Geospatial data sovereignty: publishing to PC egresses imagery-derived
      products to a GeoCatalog region — operators must ensure region/partner
      terms permit it (surface in provider config/docs).
- [x] Partner data sharing agreements: publishing derived products may be
      governed by imagery source terms — publisher responsibility; note in docs.
- [x] Data retention: `published/{datasetId}/` copies persist until unpublish or
      project delete — add GC (open question).
- [x] Audit logging: log publisher, target, dataset, status transitions.
- [x] Component Governance: new Python deps (`azure-identity`, `pystac`,
      `geopandas`, `pyogrio`, `shapely`) scanned in CI. `geopandas`/`pyogrio`
      overlap existing GDAL-stack deps — verify no new native surface.

## Rollback Assessment

- **Reversibility:** fully reversible.
- **Cosmos data:** `PUBLISHED_DATASETS` `index` doc is additive; reverting code
  leaves it inert (unknown type ignored). Optional delete.
- **Blob data:** `published/*` prefixes are inert extra blobs; optional cleanup.
  PC collections/items persist in the GeoCatalog until deleted via its API
  (out-of-band, documented).
- **API:** all new endpoints are additive; existing endpoints unchanged →
  backward-compatible.
- **Estimated rollback time:** < 15 min (revert deploy); external PC cleanup is
  best-effort and asynchronous.
