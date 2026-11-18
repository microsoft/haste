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
| hastegeo | VRT bytes disguised as TIFF/GPKG are rejected before GDAL/Fiona opens; TIFF opens use the GTiff allowlist; GPKG reads use the GPKG allowlist; upload chunk 0 is validated before storage; configuration audit; self-check policy |
| TiTiler | Tiles render with the VRT driver registered (disabling it breaks reprojection); tiles, including reprojected sources, through the app; negative tests for inline VRT, `vrt://`, remote VRT documents (raw band, Python pixel function, local or internal sources) and `/vsi` paths |
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

## Security rebuild

- Verify source and upstream patch hashes, reject missing or modified patches,
  and exercise the patched OpenSSL security regression tests.
- Confirm actual SQLite build options and whether the SQLite command-line
  shell is present in the shipped wheels, Function packages and worker images.
- Verify the manifest and SBOM record the exact source versions and applied
  patch identities. Run both existing blocking vulnerability scans.
- Test separately declared candidate and published builds, including mixed
  consumer versions, unpublished assets and downgrade attempts.
- Run all existing native, GDAL hardening, target-image, package, provenance,
  license and functional smoke tests against the candidate.

The first candidate built successfully and passed the upstream OpenSSL
regression recipes, runtime/binding smoke tests and Function/imageryprep
target-image smokes. Its SBOM scan still reported the SQLite CLI advisory and
five version-based OpenSSL matches. The initial training smoke exposed a
candidate-versus-published wheel mismatch; the selection fix requires a new
complete CI run. The artifact scan must also run independently of SBOM failure.
