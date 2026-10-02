# Test Plan: GDAL 3.13 Native Runtime

## Build-time tests

These run in the runtime build workflow, inside each target base image:

- the Functions Python 3.11 image;
- the imageryprep base;
- the training base.

| Test | Proves |
|---|---|
| Source hashes | Every input matches `sources.lock` and `requirements-build.txt` |
| Import and report | All five bindings import; the report shows one libgdal and one libproj; versions are 3.13.3 and 9.8.1 |
| Manifest equality | Registered drivers and VSI prefixes equal the manifest |
| Probes | VRTs using a raw band or a Python pixel function don't open; inline VRT doesn't open when VRT is skipped |
| Functional | GeoTIFF/COG read and write; DEFLATE, LZW and ZSTD; `gdal.Warp` reprojection; `gdal.BuildVRT` mosaic from opened datasets; JPEG preview; GPKG and GeoJSON vector read and write through fiona and pyogrio; `pyproj` transforms; rasterio `WarpedVRT` |
| Network handler | `/vsicurl/` range reads against a local HTTPS test server, with no internet |

## Application tests

| Area | Test |
|---|---|
| hastegeo | Untrusted downloads with VRT content are rejected; allowed drivers at every untrusted open; configuration audit; self-check policy |
| TiTiler | Tiles, including reprojected sources, through the app; negative tests for inline VRT, `vrt://`, remote VRT documents (raw band, Python pixel function, local or internal sources) and `/vsi` paths |
| Guards | Dependency pins come only from the runtime set and match everywhere; forbidden GDAL settings are rejected across infrastructure, scripts, Dockerfiles and app settings |

## Deployment evidence

| Criterion | Evidence |
|---|---|
| GDAL 3.13.3 in the deployed process | Runtime report logged at startup by each app and each Batch task |
| Bindings match libgdal | Report: one libgdal path; every binding at 3.13.3 |
| Raw-VRT and Python pixel functions disabled | Report configuration plus probe results |
| No caller control over GDAL configuration | Configuration audit test plus TiTiler negative tests |
| Driver and VSI inventory | Published manifest plus the live report |
| No deployment relaxes the restrictions | Guard test plus deployed app-settings scan |
