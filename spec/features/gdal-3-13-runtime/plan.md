# Plan: GDAL 3.13 Native Runtime

| Phase | Task | Agent | Status |
|---|---|---|---|
| 0 | Spec and ADR-0007 | `backend-dev` | done |
| 0 | Baseline runtime report from every current runtime | `backend-dev` | pending |
| 1 | Source lock (`native/gdal-runtime/sources.lock`) and verified fetcher | `backend-dev` | done |
| 1 | Runtime package `haste_gdal_runtime` (configure, harden, report, verify, CLI) | `backend-dev` | drafted, not yet run against a real build |
| 1 | Build scripts and shared runtime packaging | `backend-dev` + `gis` | pending |
| 1 | Build workflow: manifest, SBOM, notices, scan gate, attestation, smoke tests | `backend-dev` | pending |
| 1 | Approval-gated publish to `haste-binaries`; license review | `backend-dev`, `security` | pending |
| 2 | hastegeo self-check policy; `harden_gdal()` rework | `backend-dev` | pending |
| 2 | Untrusted-input content check and driver allowlist at open; configuration audit | `gis` | pending |
| 2 | GDAL hardening settings in Bicep, `deploy_apps.sh`, Dockerfiles and compose | `backend-dev` | pending |
| 3 | TiTiler: hash-locked dependencies on the runtime; startup self-check; VRT driver policy; negative tests | `backend-dev` | pending |
| 4 | Build-once Function App packages; `--no-build` deploy; post-deploy verification | `backend-dev` | pending |
| 5 | imageryprep and training images (training to Python 3.11); local dev and CI test environments | `backend-dev` + `gis` | pending |
| 6 | Dependency pin guards, forbidden-configuration guard, docs, close the GDAL exception | `backend-dev` | pending |
| 7 | Dev rollout, runtime evidence, production after approval | `backend-dev` | pending |

Validation for every phase: `backend-validation`. New native dependencies:
`security` audits them and `security-validation` confirms.

## Status and next steps

What exists:

- `native/gdal-runtime/sources.lock`: nine native sources with SHA-256. All
  nine downloads were checked against these hashes.
- `native/gdal-runtime/fetch_sources.py`: downloads and verifies the lock;
  any mismatch is fatal.
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
  - The policy logic was exercised with synthetic reports. Nothing has run
    against a real libgdal yet.

Next, in order:

1. Unit tests for the pure-Python parts: lock parsing, `mapped_libraries`,
   `configure`, `skip_list`, `evaluate`.
2. Add the five binding sdists to the lock: GDAL 3.13.3, rasterio 1.4.4,
   fiona 1.10.1, pyogrio 0.13.0, pyproj 3.7.2.
3. Write the hash-locked build toolchains. Two are needed (see below).
4. `build.sh`, run in the pinned builder image: zlib, libdeflate, zstd,
   libjpeg-turbo, OpenSSL, curl, sqlite, PROJ, then GDAL. Then:
   - check that every non-system dependency resolves to the install prefix;
   - write the manifest with `python -m haste_gdal_runtime manifest`;
   - assert the manifest's drivers equal the expected set below.
5. `assemble_wheels.py`:
   - build the binding wheels;
   - merge them with the runtime package, with only one `.dist-info`
     (auditwheel rejects more than one);
   - run `auditwheel repair` once;
   - split back into one wheel per distribution with `+haste.N` versions;
   - make each binding wheel require the exact runtime wheel.
6. `smoke_test.py`: install the wheels in the Functions Python 3.11 image and
   the Batch base image, run `python -m haste_gdal_runtime verify`, read and
   write the allowed formats, and do one HTTPS `/vsicurl/` read.
7. `.github/workflows/gdal-runtime-build.yml`: unit, build and smoke jobs,
   with no write credentials. Publishing and attestation are a separate,
   approval-gated change.

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
- Adding `-DCPL_VSIL_CURL_HEADER_FILE_KVP_DISABLED` removes `header_file=`
  from `/vsicurl?`. The runtime setting `CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED`
  accepts `NO` (disabled), `ONLY_IN_TEMP` (the default) or `YES`.
- Turn optional drivers off, then name the ones to keep:
  - `GDAL_BUILD_OPTIONAL_DRIVERS=OFF` and `OGR_BUILD_OPTIONAL_DRIVERS=OFF`.
  - GTiff, VRT, GeoJSON and Shape are switched back on automatically unless
    they are set explicitly, so set `GDAL_ENABLE_DRIVER_GTIFF=ON`,
    `GDAL_ENABLE_DRIVER_VRT=ON`, `OGR_ENABLE_DRIVER_GEOJSON=ON` and
    `OGR_ENABLE_DRIVER_SHAPE=OFF`.
  - GPKG needs `OGR_ENABLE_DRIVER_SQLITE=ON`.
  - MEM is always built.
- The expected driver inventory is GTiff, COG, VRT, MEM, PNG, JPEG, GeoJSON,
  GeoJSONSeq, ESRIJSON, TopoJSON, GPKG and SQLite. Every driver registration
  is conditional, so nothing else should appear. In 3.13, "Memory" is a
  hidden alias of MEM and is not in the driver list.
- Dependency selection:
  - `GDAL_USE_EXTERNAL_LIBS=OFF` and `GDAL_USE_INTERNAL_LIBS=OFF`.
  - Then turn on `GDAL_USE_CURL`, `GDAL_USE_SQLITE3`, `GDAL_USE_ZLIB`,
    `GDAL_USE_DEFLATE`, `GDAL_USE_ZSTD` and `GDAL_USE_JPEG`.
  - Then turn on `GDAL_USE_TIFF_INTERNAL`, `GDAL_USE_GEOTIFF_INTERNAL`,
    `GDAL_USE_PNG_INTERNAL` and `GDAL_USE_JSONC_INTERNAL`. json-c is required.
- `gdal-config` is installed even with `BUILD_APPS=OFF`.

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
