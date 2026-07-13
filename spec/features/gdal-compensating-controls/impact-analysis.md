# Impact Analysis: GDAL Deferral Compensating Controls

## Blast Radius

| Area | Touched? | Notes |
|---|---|---|
| Imagery read/write (GTiff/COG/VRT/JPEG) | Yes (indirect) | Driver allowlist must include every needed driver — audited. A wrong exclusion would break processing. |
| Vector I/O (GPKG/GeoJSON) | Yes (indirect) | GPKG/GeoJSON/Memory allowlisted. |
| Chunked upload | Yes | New size cap + magic-byte check; error path already returns 400. |
| Remote imagery download | Yes | Redirect refusal + size cap; behavior change for redirecting sources (intended). |
| API request/response shapes | No | No endpoint or schema change. |
| Cosmos/Blob/Data Lake schemas | No | None. |
| UI | No | None. |
| Azure Batch job orchestration | No | Only env (`GDAL_SKIP`) added to images. |

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Allowlist omits a driver the pipeline needs → processing breaks | Medium | High | Full driver audit done; unit test asserts allowlisted drivers present; imagery smoke test (COG/JPEG/GPKG/GeoJSON) before merge |
| `harden_gdal()` not called early enough on some path | Medium | High | Wire at module import of every parse site + workflow/training `main()`; idempotent so over-calling is safe |
| Subprocess gdalwarp/translate still loads HDF4 | Medium | High | `GDAL_SKIP` env in both Dockerfiles covers CLI tools |
| Download size cap too low → breaks large legitimate COGs | Medium | Medium | Generous default (8 GiB) + env-tunable; caps target pathological inputs |
| Magic-byte sniff rejects a valid TIFF/GPKG variant | Low | Medium | Sniff accepts both TIFF byte orders (`II*\0`/`MM\0*`) and the GPKG/SQLite header; unit-tested |
| rasterio uses its own GDAL and ignores in-process deregister | Low | High | rasterio shares the same libgdal process-wide; deregistration affects it. `GDAL_SKIP` env is belt-and-suspenders |

## Dependencies

- No new Python packages. Uses stdlib + existing `osgeo.gdal`/`ogr`,
  `requests`.
- Depends on the merged pyarrow work only incidentally (same files
  touched earlier are unrelated lines).

## Backward Compatibility

- Upload/download size caps and redirect refusal are new constraints.
  Defaults are generous; redirect refusal matches the existing
  footprint-path behavior, so this only tightens an inconsistent gap.
- No persisted data changes; no migration.

## Rollback

- Pure code/env revert (see [rollout.md](rollout.md)). Reverting restores
  the prior behavior with zero data implications.

## Security Review Lens

- Directly reduces exploitability of CVE-2026-8087/8088/8212 by removing
  the HDF4/HDF-EOS dispatch target from untrusted-input paths and bounding
  ingestion. Net security posture strictly improves.
