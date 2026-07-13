# Technical Design: GDAL Deferral Compensating Controls

## Overview

Add a single hardening module (`hastegeo.core.utils.gdal_security`) that
(a) restricts GDAL/OGR to an allowlist of drivers at process startup, and
(b) provides magic-byte sniffing + size-limit helpers. Wire it into every
module that opens geospatial files and every ingestion boundary, and set a
`GDAL_SKIP` denylist env in the containers so subprocess GDAL CLI tools are
covered too. No API surface, data model, or UI changes.

## Architecture

### Component Diagram

```
   upload boundary            download boundary           parse boundary
 ┌─────────────────┐        ┌────────────────────┐      ┌──────────────────┐
 │ UploadFileBy-   │        │ ImageryDownloader  │      │ imagery.py /aoi  │
 │ Chunk → uploader│        │ .download_*        │      │ /footprints/...  │
 └───────┬─────────┘        └─────────┬──────────┘      └────────┬─────────┘
         │ size cap + magic-byte      │ size cap +               │ gdal.Open /
         │ sniff (declared==actual)   │ allow_redirects=False    │ rasterio.open
         ▼                            ▼                          ▼
        ┌──────────────────────────────────────────────────────────────┐
        │           hastegeo.core.utils.gdal_security                    │
        │  harden_gdal()  ·  sniff_file_type()  ·  assert_* · size envs  │
        └───────────────────────────────┬──────────────────────────────┘
                                         │ deregisters non-allowlisted drivers
                                         ▼
                        GDAL/OGR driver manager (in-process)
                        + GDAL_SKIP env → subprocess gdalwarp/translate
```

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| `gdal_security` | `hastelib/src/hastegeo/core/utils/gdal_security.py` | Driver allowlist enforcement, magic-byte sniffing, size constants | Python / GDAL |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| Imagery utils | `core/utils/imagery.py` | Replace bare `gdal.UseExceptions()` with `harden_gdal()` at import |
| AOI / footprints / assessment / labels | `core/utils/aoi.py`, `core/utils/footprints.py`, `core/utils/assessment.py`, `core/processors/labels.py` | `harden_gdal()` at import (idempotent) |
| Imagery downloader | `core/utils/downloader.py` | `allow_redirects=False`, refuse 3xx, byte-cap downloads, content-type sniff |
| Uploader | `core/processors/uploader.py` | Per-chunk + cumulative size cap; magic-byte check on finalize vs declared `data_format` |
| Workflow entrypoints | `workflows/prepare_imagery.py`, `workflows/zip_artifacts.py` | `harden_gdal()` at `main()` start |
| Training entrypoints | `docker/training/code/{run_workflow,inference,create_masks}.py` | `harden_gdal()` at `main()` start (imports from copied `hastegeo`) |
| Containers | `docker/imageryprep/Dockerfile`, `docker/training/Dockerfile` | `ENV GDAL_SKIP="HDF4 HDF4Image HDF5 HDF5Image netCDF"` |

## API Design

No new HTTP endpoints, queue messages, or response-shape changes.

### Internal Interfaces (hastegeo)

| Module | Function/Class | Signature | Description |
|---|---|---|---|
| `core/utils/gdal_security` | `harden_gdal` | `harden_gdal(*, force: bool = False) -> None` | Idempotent. `UseExceptions()` on gdal+ogr; deregister every driver not in the allowlist. No-op after first run unless `force`. |
| `core/utils/gdal_security` | `sniff_file_type` | `sniff_file_type(path: str) -> str \| None` | Magic-byte detection → `"tiff"`/`"gpkg"`/`"png"`/`"jpeg"`/`"geojson"`/`None`. |
| `core/utils/gdal_security` | `assert_allowed_upload_format` | `assert_allowed_upload_format(filename: str, declared: str) -> None` | Extension-allowlist boundary check; raises `ValueError`. |
| `core/utils/gdal_security` | `assert_matches_declared` | `assert_matches_declared(path: str, declared: str) -> None` | Sniffed type must match the declared `data_format`; raises `ValueError`. |
| `core/utils/gdal_security` | `max_upload_bytes` / `max_download_bytes` | `() -> int` | Read env knobs with safe defaults. |
| `core/utils/gdal_security` | `ALLOWED_RASTER_DRIVERS`, `ALLOWED_VECTOR_DRIVERS`, `DISABLED_DRIVERS_ENV` | constants | Allowlists + the `GDAL_SKIP` denylist string. |

### Driver allowlist (audited)

- **Raster:** `GTiff`, `COG`, `VRT`, `JPEG`, `PNG`, `MEM`
  - `GTiff` — `CreateCopy`, default rasterio writes, `is_gtiff`; COG creation depends on it.
  - `COG` — `gdal.Translate(format="COG")`, training COG conversion.
  - `VRT` — `gdal.BuildVRT` mosaicking; inference accepts `.vrt` input.
  - `JPEG` — `convert_tif_to_jpeg`.
  - `PNG` — included per scope (visualization/defensive; harmless).
  - `MEM` — in-memory scratch datasets.
- **Vector:** `GPKG`, `GeoJSON`, `Memory`
  - `GPKG` — footprint read/write, training merge output.
  - `GeoJSON` — AOI/label reads (`gpd.read_file`, `fiona.open`).
  - `Memory` — pyogrio/geopandas in-memory scratch.

### Enforcement mechanism

- **In-process (the security-critical path):** iterate the registered
  drivers via `gdal.GetDriverCount()`/`gdal.GetDriver(i)` and
  `ogr.GetDriverCount()`; `Deregister()` any whose short name is not in the
  allowlist. This is version-independent and removes the HDF4/EOS dispatch
  target entirely, so `gdal.Open()` on a malicious HDF4 file fails with "not
  recognised" instead of entering the vulnerable parser.
- **Subprocess / CLI runtime:** `GDAL_SKIP` env (denylist of
  `HDF4 HDF4Image HDF5 HDF5Image netCDF`) set in the Dockerfiles so
  `gdalwarp`/`gdal_translate`/`gdaladdo` spawned by the workflows also refuse
  the vulnerable drivers. (`GDAL_SKIP` is read at registration; a denylist is
  the only form expressible via env, and these are the CVE-relevant families.)

## Behavior & Logic

### Core Flow (control points)

1. Process starts → first module that imports `gdal_security` calls
   `harden_gdal()` → allowlist enforced once, logged.
2. **Upload:** `UploadFileByChunk` → `FileUploader.save_chunk`/`finalize`:
   reject if any chunk pushes the cumulative size over `max_upload_bytes`;
   on finalize, `sniff_file_type(assembled)` must match the declared
   `data_format` (tif↔tiff/geotiff, gpkg) before storage/parse.
3. **Imagery download:** `ImageryDownloader.download_imagery_from_urls`:
   allowlist host (existing) → `requests.get(..., allow_redirects=False,
   stream=True)` → refuse 3xx → stream with a running byte cap →
   content-type sniff.
4. **Parse:** any `gdal.Open`/`rasterio.open`/`fiona.open` now runs against
   the hardened driver set.

### Edge Cases

| Case | Expected Behavior |
|---|---|
| Upload exceeds `max_upload_bytes` | `ValueError` → HTTP 400; partial chunks cleaned up |
| Uploaded `.tif` is actually an HDF4/zip/other | magic-byte mismatch → `ValueError` → 400 before GDAL sees it |
| Allowlisted host 302-redirects to an internal host | download refused (`RuntimeError`/skip), logged |
| Remote imagery exceeds `max_download_bytes` | download aborted mid-stream, file discarded |
| Legitimate multi-GB COG | allowed — default download cap is generous and env-tunable |
| `harden_gdal()` called many times | idempotent no-op after first |
| A needed driver was wrongly excluded | caught by imagery smoke test + unit test asserting allowlisted drivers are present |

### Error Handling

| Error Condition | Response | Recovery |
|---|---|---|
| Size/type rejection at upload | `ValueError` → 400 | user re-uploads a valid file |
| Redirect/oversize at download | log + skip URL (imagery) / `RuntimeError` (footprint) | job continues with already-valid inputs where possible |
| GDAL open of disallowed driver | GDAL `RuntimeError` (UseExceptions) | surfaced as processing failure, logged |

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `HASTE_MAX_UPLOAD_BYTES` | int | 5 GiB | App Settings / compose env | Cap for assembled chunked uploads |
| `HASTE_MAX_IMAGERY_DOWNLOAD_BYTES` | int | 8 GiB | App Settings / compose env | Cap for remote imagery fetch |
| `GDAL_SKIP` | str | `HDF4 HDF4Image HDF5 HDF5Image netCDF` | Dockerfiles | Drivers GDAL refuses to register (subprocess/runtime) |

> Defaults are deliberately generous (satellite COGs are legitimately large);
> the goal is to bound pathological/hostile inputs, not to rate-limit normal use.

## Observability

- **Logs:** `harden_gdal()` logs the count + names of disabled drivers once at
  startup; every rejection (size, magic-byte mismatch, redirect) logs at
  WARNING with the boundary + reason (no full URLs/paths beyond host/name).
- **Metrics:** existing Azure Monitor; rejections surface as 4xx on the upload
  route and as WARNING logs in the workflow containers.

## Open Questions

- [ ] None blocking. Default size caps may be tuned after observing real
      imagery sizes in production (env-tunable, so no code change needed).
