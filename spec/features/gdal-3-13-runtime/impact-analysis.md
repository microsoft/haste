# Impact Analysis: GDAL 3.13 Native Runtime

## Current state

| Runtime | Python | GDAL builds in one process |
|---|---|---|
| `hastefuncapi`, `hastefuncqueues` | 3.11 | GDAL 3.9.2 bindings wheel, plus the copies bundled in rasterio, pyogrio and fiona |
| `titilerfuncapi` | 3.11 | rasterio's bundled copy; dependencies besides `titiler.application` are unpinned |
| imageryprep image | 3.11 | GDAL 3.9.2 wheel, plus rasterio, fiona and pyogrio copies |
| training image | 3.10 (conda) | conda GDAL < 3.9, plus rasterio's bundled copy |

Function Apps resolve their dependencies on Azure at deploy time.

## Findings that shape the design

### Several driver registries per process

Each libgdal copy has its own registry. `harden_gdal()` deregisters drivers
in the osgeo copy only. The rasterio, fiona and pyogrio copies only see the
`GDAL_SKIP` denylist, and only if it is set before they register drivers.

### Untrusted downloads can be parsed as VRT

Downloaded imagery is size-checked but not content-checked. It is then opened
with every registered driver, VRT included. A VRT document served from an
allowlisted host would be parsed as VRT, and could reference local files or
internal URLs. GDAL 3.12's raw-band restrictions don't cover ordinary VRT
sources. The fix is a content check plus an explicit driver allowlist at
open.

### VRT is needed internally

`gdal.BuildVRT` builds mosaics in imagery preparation, and training inference
reads HASTE-produced `.vrt` files. The tile server never needs VRT as input,
but rasterio's `WarpedVRT` must be tested with the driver skipped.

### Network handlers can't be selectively disabled at runtime

GDAL 3.13 has no runtime allowlist for individual virtual file system
handlers. The network handlers come with libcurl, which label tasks and tile
serving need. Controls are therefore build-time removal where possible, plus
HTTPS-only and host allowlisting at the application layer.

## Blast radius

**Code paths.** Every GDAL read and write path:

- imagery preparation (warp, mosaic, COG, JPEG preview);
- label tasks and footprints;
- prediction GeoPackages and assessment reports;
- publishing rasters;
- tile serving.

**Pipelines:**

- runtime build and publish;
- `deploy_apps.sh`, `deploy-apps.yml` and the azd hooks;
- dependency validation;
- image builds.

**Local dev:** setup scripts, Docker Compose and the CI test environment.

**Deploying older branches.** After this lands, deploying a Function App from
a branch without these changes reinstalls the old GDAL. The rollout notes
that.

## Risks

| Risk | Mitigation |
|---|---|
| rasterio 1.4.4 or fiona 1.10.1 fails to build or behave against GDAL 3.13 | Compatibility tests in the build. Fallback: Python 3.12 with rasterio 1.5. |
| rio-tiler reprojection needs the VRT driver | Keep it registered for TiTiler, and restrict the reader to GTiff/COG |
| Two PROJ copies conflict over `proj.db` | pyproj is built against the runtime's PROJ |
| Package size or cold start grows on Flex Consumption | Measured. The minimal driver set should shrink packages compared with today's several copies. |
| HASTE now owns patching of vendored native libraries | Scheduled rebuilds, SBOM vulnerability gate, documented owner |
| The Functions worker's glibc is undocumented | `manylinux_2_28` baseline, proven by the self-check on a dev deployment |
