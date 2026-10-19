# Plan: GDAL 3.13 Native Runtime

| Phase | Task | Agent | Status |
|---|---|---|---|
| 0 | Spec and ADR-0007 | `backend-dev` | done |
| 0 | Baseline runtime report from every current runtime | `backend-dev` | report script implemented; collection from current runtimes pending |
| 1 | Source lock (`native/gdal-runtime/sources.lock`) and verified fetcher | `backend-dev` | done |
| 1 | Runtime package `haste_gdal_runtime` (configure, harden, report, verify, CLI) | `backend-dev` | implemented; manifest records all binding versions and startup checks compare them with installed wheels; 47 native runtime tests pass locally |
| 1 | Build scripts and shared runtime packaging | `backend-dev` + `gis` | implemented; six-wheel artifact built and downloaded |
| 1 | Build workflow: manifest, SBOM, notices, scan gate, attestation, smoke tests | `backend-dev` | native build and consumer smokes are implemented; the latest private run failed in the TiTiler VRT smoke because it skipped `configure(policy)`; fixed at commit `16d6735`, awaiting upstream CI validation |
| 1 | Approval-gated publish to `haste-binaries`; license review | `backend-dev`, `security` | private publisher verifies provenance, exact source-lock/SBOM match, wheel licenses, checksums and immutable upload; local tests pass; Microsoft OSS approval and upstream confirmation still required |
| 2 | hastegeo self-check policy; `harden_gdal()` rework | `backend-dev` | implemented in the consumer integration; single-libgdal/libproj and per-binding version checks fail closed, and required consumers enable fail-closed startup |
| 2 | Untrusted-input content check and driver allowlist at open; configuration audit | `gis` | uploaded chunk headers, downloaded TIFFs and user GPKG inputs are content-checked; imagery opens are GTiff-only and GPKG reads use Fiona's GPKG allowlist; audit and runtime validation of remaining workflows are still required |
| 2 | GDAL hardening settings in Bicep, `deploy_apps.sh`, Dockerfiles and compose | `backend-dev` | implemented in private fork: runtime-required flag and `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` are wired through deployment and container surfaces; Bicep compiles; deploy script keeps old workers running until package publish succeeds, then enables fail-closed startup |
| 3 | TiTiler: hash-locked dependencies on the runtime; startup self-check; VRT driver policy; negative tests | `backend-dev` | startup policy and VRT-disabled reprojection smoke are implemented; the smoke now configures policy before startup verification; upstream CI must validate the fix; request-source restrictions and `/vsi` negative tests remain |
| 4 | Build-once Function App packages; `--no-build` deploy; post-deploy verification | `backend-dev` | package builder and verified `--no-build` deploy path are implemented; target-image package/import smokes and post-deploy runtime diagnostics must pass before rollout |
| 5 | imageryprep and training images (training to Python 3.11); local dev and CI test environments | `backend-dev` + `gis` | imageryprep and training pin the shared wheels; training uses Python 3.11 and in-process APIs instead of GDAL command-line tools; the full-environment smoke and local developer setup remain unverified |
| 6 | Dependency pin guards, forbidden-configuration guard, docs, close the GDAL exception | `backend-dev` | in progress: repo guard rejects weakened GDAL settings across infra, workflows, scripts, API and Docker config; release-package guards added; old dependency pins and exception stay until runtime consumer packages are built and approved |
| 7 | Dev rollout, runtime evidence, production after approval | `backend-dev` | pending |

Validation for every phase: `backend-validation`. New native dependencies:
`security` audits them and `security-validation` confirms.

## Status and next steps (2026-10-19)

What exists:

- `native/gdal-runtime/sources.lock`: nine native sources with SHA-256. All
  nine downloads were checked against these hashes.
- `native/gdal-runtime/fetch_sources.py`: downloads and verifies the lock;
  any mismatch is fatal.
- `native/gdal-runtime/baseline_report.py`: emits versions from every
  importable binding, mapped libgdal/libproj paths, driver and VSI inventories,
  and a safe allowlist of GDAL/PROJ config values. Reports from the existing
  Function Apps and Batch images still need to be collected.
- `native/gdal-runtime/haste_gdal_runtime/`: the runtime package.
  - `configure(policy)` sets the operator settings, pins `GDAL_DATA`,
    `PROJ_DATA` and `GDAL_CONFIG_FILE` to the package, and puts disallowed
    drivers in `GDAL_SKIP`.
  - `harden(policy)` deregisters disallowed drivers and removes disallowed
    virtual file systems.
  - `report()` collects the evidence; `evaluate()` and `verify_or_raise()`
    compare it with the manifest and policy.
  - `secure_startup(policy)` runs harden, then verify.
  - The CLI offers `report`, `verify` and `manifest`.
  - Policy logic has synthetic unit coverage; the runtime also passed a
    real-libgdal smoke check with GDAL 3.13.3 and PROJ 9.8.1.

Next, in order:

1. Update the existing upstream draft PR with the integrated consumer work,
   then validate the exact head in upstream CI. The latest private run failed
   because the TiTiler VRT smoke called `secure_startup()` without first
   applying `configure(policy)`. The fix is committed locally as `16d6735`;
   the native runtime unit suite passes (47 tests). This fix has not yet been
   validated by a complete CI build.
2. Complete remaining GDAL open-path and compatibility evidence, including
   the full training environment, all target-image package imports, and
   supported imagery, tile, and training workflows. Baseline reports from
   existing runtimes also remain outstanding.
3. Finish the license and supply-chain review before publishing immutable
   wheels. No artifact has been published, and no environment has been
   deployed. After upstream CI and review pass, keep deployment and release
   gated on the required approvals and dev runtime evidence.

## Verified build facts

Each fact below was checked in the GDAL 3.13.3, PROJ 9.8.1 and curl 8.22.0
sources, or in the published package metadata. They replace the matching
open questions in `design.md`.

GDAL CMake options:

- `GDAL_VRT_ENABLE_RAWRASTERBAND=OFF` leaves `VRTRawRasterBand` out of the
  build. The VRT driver advertises `GDAL_VRT_ENABLE_RAWRASTERBAND=YES`
  metadata only when raw bands are compiled in, so its absence is evidence.
- `GDAL_AUTOLOAD_PLUGINS=OFF` defines `GDAL_NO_AUTOLOAD`. Native plugin
  loading becomes a no-op, and so does Python driver loading, because the
  search path list is empty. Driver and plugin paths are then ignored.
- Adding `-DGDAL_VRT_DISABLE_PYTHON` to the C++ flags forces
  `GDAL_VRT_ENABLE_PYTHON` to `NO` whatever the configuration.
- Setting `CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED=NO` rejects `header_file=`
  in `/vsicurl?`. The setting also accepts `ONLY_IN_TEMP` (the default) or
  `YES`; the runtime package pins it to `NO`.
- Turn optional drivers off, then name the ones to keep:
  - `GDAL_BUILD_OPTIONAL_DRIVERS=OFF` and `OGR_BUILD_OPTIONAL_DRIVERS=OFF`.
  - GTiff, VRT, GeoJSON and Shape are switched back on automatically unless
    they are set explicitly, so set `GDAL_ENABLE_DRIVER_GTIFF=ON`,
    `GDAL_ENABLE_DRIVER_VRT=ON`, `OGR_ENABLE_DRIVER_GEOJSON=ON` and
    `OGR_ENABLE_DRIVER_SHAPE=OFF`.
  - GPKG needs `OGR_ENABLE_DRIVER_SQLITE=ON`.
  - MEM is always built.
- The expected native driver inventory is GTiff, COG, VRT, MEM, PNG, JPEG,
  GeoJSON, GeoJSONSeq, ESRIJSON, TopoJSON, GPKG, SQLite, GNMDatabase and
  GNMFile. The published GDAL Python sdist includes its GNM wrapper based on
  the release-time CMake configuration and compiles it unconditionally for
  the pinned build, so `ENABLE_GNM` must remain on to supply its headers and
  symbols. The runtime manifest records both GNM drivers; HASTE's per-workflow
  allowed-driver policy adds them to `GDAL_SKIP` and deregisters them at
  startup. In 3.13, "Memory" is a hidden alias of MEM and is not in the driver
  list.
- Dependency selection:
  - `GDAL_USE_EXTERNAL_LIBS=OFF` and `GDAL_USE_INTERNAL_LIBS=OFF`.
  - Then turn on `GDAL_USE_CURL`, `GDAL_USE_SQLITE3`, `GDAL_USE_ZLIB`,
    `GDAL_USE_DEFLATE`, `GDAL_USE_ZSTD` and `GDAL_USE_JPEG`.
  - Then turn on `GDAL_USE_TIFF_INTERNAL`, `GDAL_USE_GEOTIFF_INTERNAL`,
    `GDAL_USE_PNG_INTERNAL` and `GDAL_USE_JSONC_INTERNAL`. json-c is required.
- `BUILD_APPS=OFF` omits `gdal-config`. After installing the native library,
  the build reconfigures to generate this build-only metadata script, copies
  only `gdal-config` into the build prefix and does not compile or ship GDAL
  command-line utilities. CI logs showed that the repeated `gdal-config`
  failure happened earlier than the binding-wheel build: pip inspected GDAL's
  PEP 517 metadata while fetching binding sdists, before the native runtime
  existed. The build now fetches those sdists only after it creates and exposes
  `gdal-config`; the latest run passed that stage and reached native
  compilation. A proposed compile-time definition for the `/vsicurl?`
  header-file restriction collided with a same-named C++ identifier in GDAL
  3.13.3 and has been removed in favor of the supported runtime setting above.
  The next run exposed GDAL's in-tree Python binding target using builder
  Python 3.15 without setuptools; that target is now disabled because the
  pinned CPython 3.11 bindings are built separately. The latest run compiled
  native GDAL, generated `gdal-config` and fetched all pinned binding sdists,
  then failed when the manifest loader could not find `libssl.so.3` under the
  runtime library path. OpenSSL now installs to the same `lib` directory as
  the other native dependencies. The latest run exposed a conflict between
  the native `ENABLE_GNM=OFF` setting and GDAL's published Python sdist, whose
  generated extension list still compiles `gnm_wrap.cpp`. GNM is now retained
  so the pinned binding can compile; its two drivers are explicitly captured
  in the manifest and excluded by the runtime's allowed-driver policy. The
  latest run then failed while pip prepared sdist metadata: isolated build
  dependencies caused redundant feed requests and an HTTP 429. Sdist metadata
  preparation now uses the preinstalled hash-pinned build-tools venv without
  isolation. Upstream run 38918675350 built the six-wheel artifact and passed
  runtime plus GDAL-binding offline smoke with the public PyPI fallback. The
  private validation branch adds all-binding and functional smoke, using a
  separately hash-locked set of runtime dependencies and a local TLS server
  for `/vsicurl/`. Run 38946439904 passed imports and version checks for all
  five bindings, confirmed one GDAL/PROJ library set, exercised raster/vector
  read/write, COG, reprojection, mosaic, WarpedVRT and PyProj, and read a
  raster over HTTPS with certificate verification. It uploaded the six-wheel
  artifact. Smoke-only dependencies are fetched from public PyPI with exact
  hashes to avoid internal-feed throttling. The private fork's CodeQL jobs
  completed analysis but could not upload results because code scanning is
  disabled for that repository. Private run `38955056455` passed the build,
  all-binding smoke, medium-or-higher Grype scan, and smoke tests in Functions,
  imageryprep and the training CUDA base. The current unvalidated changes also
  scan wheel artifacts alongside the SBOM. Its attestation job was skipped
  because publication attestations are restricted to upstream `microsoft/haste`
  main. The private build emits a CycloneDX inventory, notice bundle and
  checksums. License review, upstream CI validation of the latest fix, durable
  publication and dev rollout remain.

PROJ:

- Build with `BUILD_APPS=OFF`, `ENABLE_TIFF=OFF`, `ENABLE_CURL=OFF`,
  `BUILD_TESTING=OFF` and `EMBED_PROJ_DATA_PATH=OFF`.
- The build needs a `sqlite3` executable (`EXE_SQLITE3`).
- pyproj then needs `PROJ_DIR` and `PROJ_VERSION`, because there is no
  `proj` binary to query.

Virtual file systems:

- The only build switches are zlib, libarchive and curl.
- `VSIRemovePluginHandler()` (GDAL 3.9+) removes built-in handlers at run
  time, and they are not reinstalled.
- The drivers kept here use `/vsimem/`, `/vsisubfile/` and `/vsisparse/`
  internally. `/vsisparse/` serves GeoTIFF JPEG overviews.
- `/vsicurl/` and `/vsicurl?` are separate prefixes. Removing `/vsicurl?`
  disables caller-supplied curl options and keeps plain HTTPS reads.

curl and OpenSSL:

- curl's configure accepts `--disable-file`, `--disable-ftp`,
  `--disable-ipfs`, `--disable-ldap`, `--disable-ldaps`, `--disable-rtsp`,
  `--disable-dict`, `--disable-telnet`, `--disable-tftp`, `--disable-pop3`,
  `--disable-imap`, `--disable-smb`, `--disable-smtp`, `--disable-gopher`,
  `--disable-mqtt`, `--disable-websockets`, `--disable-netrc`,
  `--with-ca-fallback` and `--without-ca-bundle`.
- OpenSSL 3.5 accepts `no-apps`, `no-docs`, `no-tests`, `no-module`,
  `no-legacy`, `no-engine`, `no-dso` and `no-autoload-config`.
  - With `no-autoload-config` and a package-private `--openssldir`, the
    library never reads the host's `openssl.cnf`.
  - CA certificates then come from `CURL_CA_BUNDLE`, which `configure()`
    sets from the system bundle. The check fails when HTTPS is enabled but
    no bundle exists.

Build toolchain:

- fiona 1.10.1 needs Cython 3.0.x (`~=3.0.2`). rasterio 1.4.4 needs Cython
  3.1.x (`~=3.1.0`), and pyogrio and pyproj need 3.1 or later. Build fiona
  in its own environment.
- Shared pins: setuptools 84.0.0, wheel 0.48.0, packaging 26.3 (required by
  wheel), numpy 2.4.6 (the last line with Python 3.11 wheels) and versioneer
  0.28.
- Wheels built against numpy 2.x also run on numpy 1.x.

Images and actions:

- Builder image:
  `quay.io/pypa/manylinux_2_28_x86_64@sha256:1e102f2e9ed9b7fd8d64b29f798c76078c3fa8f14d34914d7a4045e39419d8e0`
  (tag `2026.10.02-1`).
  - It ships CPython 3.11, cmake, auditwheel and patchelf.
  - perl modules and nasm must be installed as build-only tools.
- `actions/upload-artifact`: `ea165f8d65b6e75b540449e92b4886f43607fa02`
  (v4.6.2).
- `actions/download-artifact`: `d3f86a106a0bac45b974a628896c90dbdf5c8093`
  (v4.3.0).
