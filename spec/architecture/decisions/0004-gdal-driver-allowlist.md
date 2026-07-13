# ADR-0004: Restrict GDAL/OGR to a driver allowlist for untrusted imagery

**Status:** accepted
**Date:** 2026-06-26
**Deciders:** HASTE engineering team

## Context

GDAL `3.9.2` is pinned across `hastelib` and the imageryprep/training
containers and cannot currently be upgraded to the patched 3.13 line (no
trusted prebuilt pip wheel for HASTE's runtime — see
`docs/known-vulnerabilities.md` Root Cause C). It carries three unpatched
memory-safety CVEs, the worst being **CVE-2026-8087 (NIST HIGH 7.8), a heap
overflow in the HDF4/HDF-EOS driver**. GDAL parses attacker-influenceable
satellite imagery throughout `hastegeo` (`gdal.Open`, `rasterio.open`,
`fiona`/`pyogrio`), and the processing nodes hold MSI tokens. The deferral
requires a compensating control that prevents untrusted input from reaching
the vulnerable parsers. Because GDAL identifies files by **sniffing
content, not the extension**, an extension/MIME check at the boundary is
insufficient on its own.

## Options Considered

### Option A: Driver denylist (skip HDF4/HDF-EOS/HDF5/netCDF)

- **Pros:** Small, targeted; directly covers the known CVEs; expressible as
  the `GDAL_SKIP` env var, so it also covers subprocess CLI tools.
- **Cons:** Allowlist-by-omission — any *other* GDAL driver with a future
  CVE remains reachable; must be maintained as new advisories land.
- **Impact:** `GDAL_SKIP` env in Dockerfiles; minimal code.

### Option B: Driver allowlist (register only what HASTE uses)

- **Pros:** Strongest posture — only audited, needed drivers are reachable;
  resilient to future CVEs in unused drivers; removes the HDF4/EOS dispatch
  target entirely.
- **Cons:** Risk of breaking processing if the audit misses a needed driver;
  cannot be expressed as `GDAL_SKIP` for already-registered `osgeo.gdal`, so
  it needs in-process driver deregistration.
- **Impact:** New `gdal_security.harden_gdal()` called at every parse site.

### Option C: Sandboxed/subprocess GDAL parsing

- **Pros:** Strong isolation of the parser.
- **Cons:** Large architectural change (process/container isolation, IPC),
  high effort, slows the pipeline; disproportionate for a deferral control.
- **Impact:** Significant runner/processor rework.

## Decision

Adopt **Option B (allowlist)** as the primary in-process control, with the
**Option A denylist as a complementary `GDAL_SKIP` env** for subprocess/CLI
coverage. `harden_gdal()` deregisters every driver not in the audited
allowlist:

- **Raster:** `GTiff`, `COG`, `VRT`, `JPEG`, `PNG`, `MEM`
- **Vector:** `GPKG`, `GeoJSON`, `Memory`

In-process deregistration is version-independent and removes the HDF4/EOS
code path from all `gdal.Open`/`rasterio.open`/`pyogrio` reads (which share
one libgdal per process). The `GDAL_SKIP="HDF4 HDF4Image HDF5 HDF5Image
netCDF"` env in the containers covers `gdalwarp`/`gdal_translate` spawned as
subprocesses, where only a denylist is expressible.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Hardening module | `hastelib/src/hastegeo/core/utils/gdal_security.py` | New — allowlist + `harden_gdal()` |
| Parse sites | `core/utils/{imagery,aoi,footprints,assessment}.py`, `core/processors/labels.py`, `workflows/*` | Call `harden_gdal()` at import/entry |
| Training entrypoints | `docker/training/code/{run_workflow,inference,create_masks}.py` | Call `harden_gdal()` at `main()` |
| Containers | `docker/imageryprep/Dockerfile`, `docker/training/Dockerfile` | `ENV GDAL_SKIP=...` |

### Azure Services Affected

| Service | Change |
|---|---|
| Azure Batch (imageryprep/training pools) | None structural; nodes run hardened GDAL via the rebuilt images |

## Consequences

- **Easier:** The GDAL deferral becomes defensible and auditable; future
  CVEs in unused drivers are pre-mitigated.
- **Harder:** Adding a new input/output format now requires updating the
  allowlist (a deliberate, documented gate).
- **New constraints:** All file parsing must occur after `harden_gdal()`;
  parse sites must import the module. The allowlist must be kept in sync
  with the pipeline's real format needs (covered by tests + an imagery
  smoke).
- **Docker Compose dev stack:** unaffected behaviorally; the dev imageryprep
  image gains `GDAL_SKIP` like prod.
- **CI/CD:** GDAL driver tests run in the conda/hatch env or the Docker test
  image, consistent with the existing geospatial test setup.
