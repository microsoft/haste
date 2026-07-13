# Test Plan: GDAL Deferral Compensating Controls

## Strategy

Unit tests in `hastelib/tests/` using `unittest` style (the dominant
pattern). GDAL-dependent tests require the conda/hatch env or the Docker
test image — they are skipped gracefully if `osgeo` is unavailable so the
non-GDAL subset still runs on a bare host. A manual imagery smoke confirms
no needed driver was dropped.

## Coverage Matrix

| ID | Area | Test | Type | Story |
|---|---|---|---|---|
| T-01 | Driver allowlist | After `harden_gdal()`, `gdal.GetDriverByName("HDF4")` / `HDF5` / `netCDF` are `None` | unit (GDAL) | US-001 |
| T-02 | Driver allowlist | Allowlisted drivers (`GTiff`,`COG`,`VRT`,`JPEG`,`PNG`) still present; OGR `GPKG`,`GeoJSON` present | unit (GDAL) | US-001 |
| T-03 | Idempotency | Calling `harden_gdal()` twice does not error and disables nothing extra | unit (GDAL) | US-001 |
| T-04 | Magic-byte sniff | `sniff_file_type` returns `tiff` for `II*\0`/`MM\0*`, `gpkg` for the SQLite/GPKG header, `png`/`jpeg`; `None` for junk | unit | US-002 |
| T-05 | Upload type check | `assert_matches_declared` rejects a `.tif`-declared file whose bytes are HDF4/zip | unit | US-002 |
| T-06 | Upload extension | `assert_allowed_upload_format` rejects `.hdf`/`.zip`/arbitrary, accepts `tif`/`tiff`/`geotiff`/`gpkg` | unit | US-002 |
| T-07 | Upload size cap | Cumulative size over `HASTE_MAX_UPLOAD_BYTES` raises `ValueError` (→400) and cleans partial chunks | unit (mock storage) | US-002 |
| T-08 | Download redirect | `download_imagery_from_urls` does not follow a 3xx and skips/refuses the URL | unit (mock `requests`) | US-003 |
| T-09 | Download size cap | Response exceeding `HASTE_MAX_IMAGERY_DOWNLOAD_BYTES` aborts and discards the partial file | unit (mock `requests`) | US-003 |
| T-10 | Download allowlist | Non-allowlisted host still rejected (regression of existing behavior) | unit | US-003 |
| T-11 | Existing format resolver | `_resolve_data_format` allowlist behavior unchanged | unit (existing) | US-002 |

## Files

- New: `hastelib/tests/core/utils/test_gdal_security.py` (T-01..T-06).
- New: `hastelib/tests/core/utils/test_downloader.py` (T-08..T-10).
- Extend: `hastelib/tests/core/processors/test_uploader_format.py` (T-05, T-07).

## Regression

- Existing `test_url_allowlist.py`, `test_uploader_format.py`,
  `test_footprints.py`, `test_prepare_imagery.py` must remain green.

## Manual / smoke

- In a GDAL-capable env: read a small COG, write a COG via `gdal.Translate`,
  convert a TIFF→JPEG, read+write a GPKG and read a GeoJSON — all succeed
  with the allowlist active.

## Verification environments

| Env | Runs |
|---|---|
| Bare host (no GDAL) | non-GDAL subset (sniff/size/download-mock, upload size) |
| `hatch run test:pytest` (conda) or Docker test image | full suite incl. GDAL driver tests |

> Local Docker/WSL is currently wedged — full GDAL run pending a healthy
> daemon or the conda env.
