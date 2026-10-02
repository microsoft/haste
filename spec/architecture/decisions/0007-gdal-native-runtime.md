# ADR-0007: Build a shared GDAL native runtime and deploy immutable Function App packages

**Status:** accepted
**Date:** 2026-10-02
**Deciders:** HASTE engineering team

## Context

### Too many GDAL builds, and no recipe

GDAL-bearing code in HASTE runs in several places:

- the `hastefuncapi`, `hastefuncqueues` and `titilerfuncapi` Function Apps;
- the imageryprep and training Batch images;
- local development and CI.

Each Python binding brings its own libgdal:

- the GDAL 3.9.2 wheel on `haste-binaries`, built outside the repository;
- the copies bundled inside the rasterio, fiona and pyogrio wheels;
- conda's GDAL in the training image.

A single process therefore loads several GDAL versions, each with its own
driver registry. [ADR-0004](0004-gdal-driver-allowlist.md) assumed one
libgdal per process, and that doesn't hold for wheel installs. Its
in-process allowlist only reaches the osgeo copy.

### Why the patched GDAL hasn't been adopted

Moving to the patched GDAL 3.13 line was deferred because no trusted wheel
exists for HASTE's Python 3.11 runtimes:

- Official GDAL Python releases are source-only.
- rasterio wheels that bundle a newer GDAL require Python 3.12 and bundle
  GDAL 3.12.
- pyogrio bundles GDAL 3.12.
- fiona's latest release bundles GDAL 3.9.

### Deployments aren't one artifact

Function Apps resolve their dependencies on Azure at deploy time, so dev and
prod aren't guaranteed to run the same bytes.

## Options Considered

### Option A: Wait for third-party GDAL 3.13 wheels

- **Pros:** No build infrastructure to own.
- **Cons:**
  - No date for such wheels.
  - Several libgdal copies per process remain.
  - Configuration and driver set stay outside HASTE's control.
- **Impact on HASTE components:** None. The deferral continues.

### Option B: Move to Python 3.12 and the newest third-party wheels

- **Pros:** Standard tooling.
- **Cons:**
  - Those wheels bundle GDAL 3.12, not 3.13.
  - Each binding still vendors its own copy.
  - A Python upgrade across every runtime at the same time.
- **Impact on HASTE components:** Every image and Function App changes
  Python version.

### Option C: conda-forge environments

- **Pros:** One shared libgdal 3.13 per environment, prebuilt.
- **Cons:**
  - rasterio 1.5 needs Python 3.12.
  - A conda prefix can't safely be shipped inside a Flex Consumption
    package, because of C++ runtime conflicts with the Functions worker.
  - A second packaging ecosystem.
- **Impact on HASTE components:** The images could adopt it; the Function
  Apps couldn't.

### Option D: Build the native runtime in CI, shared by every binding

- **Pros:**
  - GDAL 3.13.3 on Python 3.11.
  - One libgdal and one PROJ per process.
  - Build-time driver minimization; raw VRT bands compiled out.
  - Reviewable inputs, SBOM and provenance.
  - Usable in Function Apps and images alike.
- **Cons:**
  - HASTE owns the build.
  - HASTE owns rebuilds when a vendored component has a security fix.
- **Impact on HASTE components:** A new build pipeline. Every GDAL consumer
  switches to the runtime's wheels.

## Decision

Adopt **Option D**.

### Build the runtime

CI builds GDAL 3.13.3 and its native dependencies from pinned,
checksum-verified sources in a digest-pinned `manylinux_2_28` container:

- optional drivers off, then the audited set enabled explicitly;
- raw VRT bands compiled out;
- no GEOS, no CLI tools.

### Link every binding to it

GDAL, rasterio, fiona, pyogrio and pyproj are built against the runtime. One
`auditwheel` pass grafts the native libraries into the shared
`haste-gdal-runtime` wheel that every binding links to.

### Publish with evidence

The wheels are published to `haste-binaries`, immutable, with:

- a manifest of versions, drivers and virtual file systems;
- an SBOM;
- a provenance attestation.

### Check at startup

Every runtime runs the runtime package's self-check at startup and refuses
to start when the live process differs from the manifest or from HASTE's
policy. The policy covers:

- the expected version;
- VRT raw bands and Python pixel functions disabled;
- plugin loading disabled;
- no forbidden configuration.

### Deploy one artifact

Function App packages are built once, in the digest-pinned Functions Python
image, from hash-locked requirements. That same package is deployed with
`--no-build`. Images are deployed by digest.

### Amendment to ADR-0004

The driver allowlist moves to build time, and runtime deregistration remains
as defense in depth. With one shared libgdal, deregistration now reaches
every binding. Untrusted inputs are opened with an explicit driver allowlist
that excludes VRT.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Runtime recipe | `native/gdal-runtime/` | New: sources, build scripts, packaging, self-check |
| CI | `.github/workflows/` | New runtime build and publish workflow; dependency validation for the runtime |
| hastegeo | `hastelib/src/hastegeo/core/utils/` | Self-check policy; untrusted-open helpers |
| Function Apps | `api/*/requirements*`, `.github/scripts/deploy_apps.sh`, `azure.yaml` | Runtime wheels; build-once packages |
| Images | `docker/imageryprep/`, `docker/training/` | Runtime wheels; build-time self-check |

### Azure Services Affected

| Service | Change |
|---|---|
| Azure Functions (Flex Consumption) | Deployed from a prebuilt package (`--no-build`); GDAL hardening app settings |
| Azure Batch | Images rebuilt on the runtime |

## Consequences

**Easier:**
- Proving which GDAL runs where.
- Hardening one driver registry per process.
- Reviewing exactly what is compiled in.
- Shipping the same bytes to every environment.

**Harder:**
- HASTE owns rebuilds when GDAL, PROJ, curl, OpenSSL, SQLite or the
  compression libraries have a security fix.
- Python-version upgrades need a matching binding build.

**New constraints:**
- GDAL-linked bindings must come from the runtime set, never from PyPI
  binaries.
- Runtime and bindings must share a build number.

**Local dev:** The Docker Compose services install the same wheels, and the
local TiTiler builds from `api/titilerfuncapi`.

**CI/CD:** Adds the runtime build workflow and a hash-locked dependency
check. The deploy workflow packages Function Apps instead of building them
remotely.
