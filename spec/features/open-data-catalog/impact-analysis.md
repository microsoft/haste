# Impact Analysis: Open Data Catalog Explorer

## Scope of Change

| Component | Path | Type | Severity |
|---|---|---|---|
| Core library | `hastelib/.../core/models/projects.py` | modified (`clipBbox`) | low |
| Core library | `hastelib/.../core/utils/{url_allowlist,downloader,imagery}.py` | modified | medium |
| Core library | `hastelib/.../workflows/prepare_imagery.py`, `core/processors/imagery.py` | modified | medium |
| REST API | `api/hastefuncapi/function_app.py` (`PutLayer`) | modified | low |
| React UI | `ui/src/Components/OpenDataCatalog/*` (new) + `CreateEditImageLayer*` | new/modified | medium |
| React UI | `ui/src/util/validation.js` | modified | low |
| Docker config | `docker/nginx.conf`, `docker/docker-compose.yml` | modified | low (local dev) |

## Azure Service Impact

| Service | Change | Cost Impact |
|---|---|---|
| Blob Storage | Clipped artifacts (same paths, **smaller** when clipped) | neutral/negative |
| Queue Storage | Same queue; `clip_bbox` added to prep config | none |
| Azure Batch / imageryprep | Same image; extra `gdalwarp -te` (clip usually reduces work) | neutral |
| Static Web Apps | New UI + external fetches (Vantor/Planet/TiTiler) | none |

## Dependency Analysis

### Upstream

| Dependency | Type | Risk if Unavailable |
|---|---|---|
| Vantor S3 STAC (`vantor-opendata.s3.amazonaws.com`) | external | that source's events don't list; other source still works |
| Planet STAC (`data.source.coop`) | external | Planet events don't list/download; Vantor still works |
| TiTiler (`api/titiler`) | infra | no imagery preview/crop; footprints + add still work |
| Azure Maps | infra | with a key: satellite basemap; without: blank basemap (feature still works) |

### Downstream

| Consumer | How Affected | Breaking? | Migration? |
|---|---|---|---|
| `PutLayer` callers | new optional `clipBbox` field | no | no |
| Existing ImageLayer docs | unknown field read as `null` | no | no |
| imagery-prep workflow | clips when `clip_bbox` present | no | no |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| External catalog schema/URL drift | medium | medium | Per-source resilient fetch; discovery isolated in one module (swap-to-backend seam) |
| `data.source.coop` on the imagery allowlist → server-side fetch (SSRF surface) | low | low | Public, well-known open-data host; explicit host match; redirects not followed; size-capped |
| Clip bounds outside imagery / degenerate box | low | low | `validate_clip_bbox` (ranges + `w<e`, `s<n`) → 400 |
| Planet imagery not downloading (pre-fix) | — | — | **Fixed** — generic HTTP route in `ImageryDownloader` |

## Performance Impact

- **API:** one extra small validation on `PutLayer`. Negligible.
- **Imagery prep:** clip reduces mosaic/COG size and downstream work.
- **UI:** discovery = 2 root + N child STAC fetches on panel open; TiTiler tiles on preview.

## Security Impact

- [x] New API surface? Only an optional field on existing `PutLayer` (auth unchanged).
- [x] New allowlisted host (`data.source.coop`) fetched server-side by imagery prep — public open-data host, exact-match, no redirects, size-capped.
- [x] Azure Maps auth unchanged — uses the existing anonymous/AAD (Client-ID + backend-minted token) flow; no shared/subscription key is introduced.
- [x] `docker/nginx.conf` changes (CORS `*`, larger body, longer timeouts) are the **local dev proxy** only; production ingress/APIM must set equivalents separately.

## Compliance & Data Impact

- Imagery is CC BY-NC 4.0 (Vantor + Planet Open Data); attribution shown in the panel.

## Rollback Assessment

- **Reversibility:** fully reversible.
- **Data:** `clipBbox` is additive/optional; no backfill or blob cleanup needed.
- **API:** backward-compatible.
- **Estimated rollback time:** minutes (revert + redeploy).
