# Technical Design: GDAL 3.13 Native Runtime

## Contents

- [Overview](#overview)
- [Runtime composition](#runtime-composition)
- [Build](#build)
- [Packaging: one shared native runtime](#packaging-one-shared-native-runtime)
- [Runtime configuration and self-check](#runtime-configuration-and-self-check)
- [Untrusted input](#untrusted-input)
- [VRT and virtual file system policy](#vrt-and-virtual-file-system-policy)
- [Consumers](#consumers)
- [Publishing and supply chain](#publishing-and-supply-chain)
- [Open questions](#open-questions)

## Overview

HASTE builds GDAL 3.13.3 and its native dependencies from pinned,
checksum-verified sources in CI, and ships the result as one
`haste-gdal-runtime` wheel. Every GDAL-linked Python binding is compiled
against that runtime and linked to it, so a process loads one libgdal and one
PROJ:

- GDAL (osgeo)
- rasterio
- fiona
- pyogrio
- pyproj

The runtime wheel also carries:

- a **manifest**: component versions, compiled drivers, virtual file system
  prefixes and build options;
- a **self-check** that compares a live process against the manifest and a
  caller-supplied policy.

## Runtime composition

| Component | Version | Source | Notes |
|---|---|---|---|
| GDAL | 3.13.3 | OSGeo release tarball | Minimal driver set; raw VRT bands compiled out |
| PROJ | 9.8.1 | OSGeo release tarball | Built without curl or libtiff, so no network grid downloads |
| SQLite | 3.53.4 | sqlite.org amalgamation | Needed by PROJ (`proj.db`) and GeoPackage |
| curl | 8.22.0 | curl release tarball | HTTPS-only build, for `/vsicurl/` reads |
| OpenSSL | 3.5.9 (LTS) | OpenSSL release tarball | TLS for curl |
| zlib | 1.3.2 | zlib release tarball | DEFLATE |
| libdeflate | 1.26 | release tarball | Fast DEFLATE in GTiff |
| zstd | 1.5.7 | release tarball | ZSTD-compressed TIFFs from providers |
| libjpeg-turbo | 3.1.4.1 | release tarball | JPEG previews; JPEG-in-TIFF |
| libtiff, libgeotiff, libpng, json-c | GDAL internal copies | GDAL tarball | Keeps the external surface small |

**Python bindings, built from source distributions against the runtime:**

| Binding | Version | Why this version |
|---|---|---|
| GDAL (osgeo) | 3.13.3 | Matches the runtime; includes `gdal_array` (NumPy) |
| rasterio | 1.4.4 | Last release that supports Python 3.11 |
| fiona | 1.10.1 | Latest release |
| pyogrio | 0.13.0 | Latest release |
| pyproj | 3.7.2 | Last release that supports Python 3.11 (3.8 needs 3.12) |

**Exact pins live in `native/gdal-runtime/`:**

- `sources.lock`: URL and SHA-256 for every native tarball.
- `requirements-build.txt`: the hash-locked build toolchain and binding source
  distributions.

The build refuses any file whose hash doesn't match.

Wheels carry a local version label tied to the runtime build, for example
`rasterio 1.4.4+haste.1`. Binding wheels declare
`Requires-Dist: haste-gdal-runtime==<same build>`. pip therefore refuses to
mix bindings from one runtime build with another, or with PyPI binaries.

## Build

The build runs in a digest-pinned `manylinux_2_28` container. glibc 2.28 is
the baseline; the Functions Python image and both Batch base images are
newer.

**GDAL CMake configuration:**

| Setting | Value | Effect |
|---|---|---|
| `GDAL_BUILD_OPTIONAL_DRIVERS` / `OGR_BUILD_OPTIONAL_DRIVERS` | `OFF` | Only explicitly enabled drivers are built |
| Explicitly enabled | GTiff (includes COG), JPEG, PNG, MEM, VRT, GPKG, GeoJSON, and OGR memory | The audited set HASTE reads and writes |
| Raw VRT bands | compiled out | `VRTRawRasterBand` cannot be created, whatever the configuration |
| `GDAL_USE_CURL` | `ON` | HTTPS range reads for `/vsicurl/` (TiTiler, label tasks) |
| `GDAL_USE_ARCHIVE`, GEOS, HDF4/HDF5/netCDF, JP2, WebP, LERC and every other optional library | `OFF` | Not compiled at all |
| `BUILD_APPS` | `OFF` | No GDAL command-line tools ship |

The configuration the build actually produced is recorded in the manifest,
including drivers that GDAL always builds. The manifest is the reviewed
driver inventory.

## Packaging: one shared native runtime

The goal is that each binding links to one shared libgdal rather than
bundling its own copy. The build does that in four steps:

1. Build each binding from its source distribution against the installed
   runtime.
2. Merge all binding wheels into a single staging wheel.
3. Run `auditwheel repair` once on the staging wheel. auditwheel grafts
   libgdal, PROJ and their dependencies into one `haste_gdal_runtime.libs/`
   directory. It gives each library a hashed name, so the vendored copies
   cannot collide with system libraries of the same name, and points every
   extension module at that directory.
4. Split the repaired staging wheel back into per-distribution wheels:

| Wheel | Contents |
|---|---|
| `haste-gdal-runtime` (`py3-none-manylinux_2_28_x86_64`) | `haste_gdal_runtime.libs/` (shared libraries); `haste_gdal_runtime/` (GDAL and PROJ data, manifest, self-check) |
| `GDAL`, `rasterio`, `fiona`, `pyogrio`, `pyproj` (`cp311-cp311-manylinux_2_28_x86_64`) | The binding's own packages and dist-info, linked to `../haste_gdal_runtime.libs` |

Because auditwheel names libraries by content hash, bindings built for
another Python version in the same run link to the same runtime file names.

## Runtime configuration and self-check

`haste_gdal_runtime` provides a small API:

- **`configure()`** points `GDAL_DATA` and `PROJ_DATA` at the packaged data.
  It also sets the hardening options below as defaults when the environment
  doesn't set them. It runs before any binding is imported.
- **`report()`** returns:
  - the libgdal paths mapped into the process;
  - the version reported by libgdal and by each imported binding;
  - registered drivers, VSI prefixes, build info and the relevant
    configuration values.

  It queries the single libgdal through `ctypes`, so it doesn't need osgeo
  and works in TiTiler.
- **`verify(policy)`** returns every difference between the live process and
  the manifest plus the caller's policy, where the policy covers:
  - the expected GDAL version;
  - whether VRT is allowed;
  - the required configuration.

  `verify_or_raise(policy)` turns any difference into a startup failure.

**Hardening configuration.** The operator sets these, and `configure()`
defaults them:

| Option | Value | Notes |
|---|---|---|
| `GDAL_VRT_ENABLE_RAWRASTERBAND` | `NO` | Belt and braces; raw bands are already compiled out |
| `GDAL_VRT_ENABLE_PYTHON` | `NO` | No Python pixel functions |
| `GDAL_DRIVER_PATH` | `disable` | No plugin loading |
| `GDAL_DISABLE_READDIR_ON_OPEN` | `EMPTY_DIR` | No sibling-file discovery |
| `CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED` | `NO` | No `header_file=` in `/vsicurl?` URLs |
| `GDAL_SKIP` | `VRT` in TiTiler if compatible; otherwise unset | See [VRT policy](#vrt-and-virtual-file-system-policy) |

**Settings that are never allowed.** `verify()` fails if any of these is set:

- `GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE=ALL`
- `GDAL_VRT_PYTHON_TRUSTED_MODULES`
- `GDAL_PYTHON_DRIVER_PATH`
- a `GDAL_DRIVER_PATH` other than `disable`
- `CPL_ENABLE_PATH_TRAVERSAL_DETECTION=NO`

A CI guard rejects the same settings anywhere in the infrastructure, scripts,
Dockerfiles and app configuration.

**Probes.** `verify()` also tries to open:

- an in-memory VRT that uses a raw band;
- an in-memory VRT that uses a Python pixel function;
- in TiTiler, any VRT at all.

Each attempt must fail. A failure to fail is reported as a violation.

**Where the check runs:**

| Runtime | When | Consequence of failure |
|---|---|---|
| TiTiler | At import, before the FastAPI app exists | `/healthz` through APIM can't return 200 |
| API, queues | At hastegeo import | Function indexing fails, and the deploy verification catches it |
| imageryprep, training | As an image build step, and at Batch task start | The image doesn't build, or the task fails before touching input |

Every run logs the `report()` output. That log is the evidence that the
deployed runtime is the approved one.

## Untrusted input

**Untrusted inputs** are anything whose bytes come from outside HASTE:

- downloaded provider imagery;
- user uploads;
- user-supplied footprints.

**How they are handled:**

1. After download, the content is sniffed: TIFF for imagery, GeoPackage or
   GeoJSON for vectors. Anything else is rejected before GDAL sees it.
2. They are opened only with an explicit driver allowlist (GTiff/COG,
   GPKG/GeoJSON) through `gdal.OpenEx(..., allowed_drivers=...)`, rasterio's
   `driver=` and fiona's `enabled_drivers=`.
3. The opened datasets, not file names, are passed on to `gdal.Warp` and
   `gdal.BuildVRT`.

As a result, a VRT document can never be parsed from an untrusted input, even
in runtimes that keep the VRT driver for their own mosaics.

No request value reaches GDAL configuration, open options, driver paths or
plugin paths. Each GDAL configuration call site uses constant keys and
operator-controlled values. A test pins this.

## VRT and virtual file system policy

| Runtime | VRT driver | Why |
|---|---|---|
| TiTiler | Disabled (`GDAL_SKIP=VRT`), if tile rendering with reprojection passes | No VRT input is legitimate there. If rasterio's `WarpedVRT` needs the driver registered, the fallback keeps it but restricts the reader to GTiff/COG. |
| imageryprep | Registered | `gdal.BuildVRT` mosaics HASTE's own files; untrusted opens exclude VRT |
| training | Registered | Inference accepts HASTE-produced `.vrt` inputs; untrusted opens exclude VRT |
| API, queues | Registered, with untrusted opens restricted | Same library as the workers; no VRT inputs from callers |

**Virtual file systems.** GDAL 3.13 has no runtime option that allowlists
individual virtual file system handlers. Every network handler comes with
libcurl, and HTTPS range reads are needed. So:

- the build removes the handlers whose libraries aren't compiled in (for
  example the archive handlers that need libarchive);
- the application refuses caller-supplied `/vsi` paths and non-HTTPS URLs,
  and only accepts allowlisted hosts.

The manifest lists the handlers that remain.

## Consumers

| Consumer | How it installs the runtime | Immutable artifact |
|---|---|---|
| API, queues, TiTiler (Flex Consumption) | Hash-locked requirements that reference the runtime and binding wheels by URL, installed into `.python_packages` inside the digest-pinned Functions Python image | A deployment zip built once, recorded by SHA-256, deployed with `--no-build` |
| imageryprep | Same wheels, installed into the image virtualenv by hash | Image digest |
| training | Same wheels, installed into the conda environment (Python 3.11); conda no longer provides GDAL | Image digest |
| Local dev and CI tests | Same wheels | — |

## Publishing and supply chain

**The build job** has no write credentials. It produces:

- the wheels;
- the manifest;
- a CycloneDX SBOM;
- a license and NOTICE bundle for every vendored component;
- SHA-256 sums;
- a provenance attestation.

A vulnerability scan of the SBOM gates the job.

**An approval-gated publisher** uploads the assets to `haste-binaries`. They
are immutable and are never overwritten.

**Rebuilds** go through the same pipeline and bump the `+haste.N` build
number. They happen:

- when a vendored component or GDAL patch release has a security fix;
- otherwise on a fixed cadence.

## Open questions

- [ ] Confirm the CMake option that compiles raw VRT bands out in GDAL 3.13,
      and the full list of drivers GDAL always builds.
- [ ] Confirm whether rasterio's `WarpedVRT` works with `GDAL_SKIP=VRT`.
- [ ] Confirm whether values in a GDAL configuration file take precedence
      over environment variables. If so, ship a read-only `gdalrc` and pin
      `GDAL_CONFIG_FILE` to it.
- [ ] Measure the Function App package size and cold start against today's.
