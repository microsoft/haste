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

### Private-fork implementation status

The current private branch validates the first upload chunk before storing
it, checks downloaded imagery for TIFF content before processing, and opens
those rasters with the GTiff driver only. User-supplied footprint GeoPackages
are checked for GeoPackage content and read with Fiona's GPKG driver
allowlist. These controls are not yet an audit of every GDAL open site; the
remaining image, API, and training paths still need review and testing.
`hastegeo` now activates the shared-runtime self-check on package import, and
TiTiler has a startup hook that verifies the runtime when installed. Neither
consumer currently installs the new wheel or sets the required-runtime flag.

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

## Native security rebuild

The vulnerability scanner identifies SQLite 3.53.4 and OpenSSL 3.5.9 in the
published runtime inventory. These findings do not by themselves establish
reachability through a HASTE workflow.

| Area | Finding | Candidate and review gate |
|---|---|---|
| SQLite library | Multiple reported memory-safety and denial-of-service findings affect versions before 3.54.0 | Build 3.54.1 from an upstream-verified archive and run geospatial compatibility tests |
| SQLite CLI | CVE-2026-119586 affects `.recover` output replay; SQLite identifies a trunk fix but no fixed release was identified | Inventory the candidate archives and target images; security review must assess actual exposure |
| OpenSSL | Reported issues involve QUIC, AES-GCM-SIV, EC key generation, TLS, PEM and certificate verification | Apply hash-locked upstream 3.5-branch fixes and regression tests; preserve the real source version in the SBOM |

The published runtime wheel was inspected with its release SHA-256 verified:
it contains `libsqlite3` and has no member named `sqlite3`. This alone does
not prove that other packages or images lack the executable, or that a renamed
executable cannot be present. Inspection of the six candidate wheels and four
packaged ZIPs verified their SHA-256 digests and found no named CLI, direct
CLI symlink, or ELF/PE binary with the expected shell markers. This heuristic
does not rule out a modified shell or an embedded archive.

SQLite identifies [check-in d684ccc9ec](https://sqlite.org/src/info/d684ccc9ec4e41d8)
as sufficient to block this attack; it modifies the recovery extension, not
the SQLite core library. The source archive includes that extension in
`shell.c`, whereas the candidate runtime ships the shared library, not the
shell. This does not mean the upstream fix was applied to the candidate.

The imageryprep and training base images contain a SQLite 3.53.4 CLI on PATH.
The tracked source search found no direct `.recover` invocation. Combined
worker-image checks found no shell in either merged filesystem and traced
the entrypoints and targeted integration tests without a CLI launch. Full
imagery and training workflows remain to be tested. Report inherited image
layers separately from the merged filesystem. Keep both vulnerability scans
blocking; do not infer worker-image applicability from the runtime archive
result.

The current vulnerability database also reports CVE-2026-84786 and
CVE-2026-95690. Their upstream fix proposals are still open, so these two
findings remain visible and blocking; they are not included in the patched
OpenSSL exceptions.

Sources: [OpenSSL advisory](https://openssl-library.org/news/secadv/20261110.txt)
and [SQLite CLI advisory](https://github.com/advisories/GHSA-2h5x-4qp8-353h).
