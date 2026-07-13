# Feature: GDAL Deferral Compensating Controls

**Status:** approved
**Author:** HASTE engineering team
**Date:** 2026-06-26
**Target Release:** next
**Priority:** P1
**Work Item:** [docs/known-vulnerabilities.md](../../../docs/known-vulnerabilities.md) — Root Cause C (Dependabot alerts #33, #34, #38)

## Summary

GDAL `3.9.2` carries three unpatched memory-safety CVEs — most notably
**CVE-2026-8087 (NIST HIGH 7.8), a heap-based buffer overflow in the
HDF4/HDF-EOS driver**. HASTE cannot upgrade to the patched GDAL 3.13 line
because no trusted prebuilt pip wheel exists for its runtime, so the
upgrade is deferred under a documented dependency exception. That
exception is only defensible if the **compensating controls** in
`known-vulnerabilities.md` Root Cause C are actually enforced in code.
This feature implements the missing/partial controls — pre-parse GDAL
driver restriction, strict size/type checks at ingestion boundaries, and
SSRF/redirect hardening of the imagery downloader — and formalizes the
weekly exception review.

## Motivation

- **Problem:** GDAL parses attacker-influenceable satellite imagery
  throughout `hastegeo`. A malicious GeoTIFF/HDF4 file delivered through an
  imagery provider or a user upload is a realistic path to the heap
  overflow, and the imageryprep/training nodes hold Managed Service
  Identity tokens with Blob/Data Lake access.
- **Who requested it:** Security triage (`docs/security-triage-2026-06-23.md`)
  escalated the GDAL CVEs above their Dependabot "Low" rating and required
  compensating controls, and the HASTE engineering team implemented them.
- **If we don't build it:** the deferral is undocumented-in-practice — the
  controls are written down but not enforced, leaving the HIGH-severity
  HDF4/EOS code path reachable from untrusted input.

## Success Criteria

- [ ] GDAL/OGR is restricted at process startup to an allowlist of the
      drivers HASTE actually uses; HDF4/HDF-EOS/HDF5/netCDF are not
      registered and cannot be dispatched from any `gdal.Open` /
      `rasterio.open` / `fiona`/`pyogrio` read.
- [ ] Every ingestion boundary (chunked upload, remote imagery download,
      user-footprint download) enforces a size cap and a content/type
      (magic-byte) check before the bytes reach GDAL.
- [ ] The imagery downloader refuses cross-host redirects (SSRF guard),
      matching the existing footprint-download path.
- [ ] `known-vulnerabilities.md`, `security-configuration.md`, and
      `triage-process.md` reflect the implemented controls and a formal
      weekly-review cadence with an explicit exit criterion.
- [ ] All new/changed behavior is covered by unit tests and the imagery
      pipeline still produces correct COG/JPEG/GPKG/GeoJSON output.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/` | New `utils/gdal_security.py`; hardening wired into `utils/imagery.py`, `utils/aoi.py`, `utils/footprints.py`, `utils/assessment.py`, `utils/downloader.py`, `processors/labels.py`, `processors/uploader.py` |
| `api/hastefuncapi/` | `UploadFileByChunk` already surfaces `ValueError` → 400; no signature change |
| `docker/` | `GDAL_SKIP` env in `imageryprep/Dockerfile` and `training/Dockerfile` |

## Related Specs

| Spec | Relationship |
|---|---|
| [ADR 0004 — GDAL driver allowlist](../../architecture/decisions/0004-gdal-driver-allowlist.md) | records the allowlist-vs-denylist decision |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [plan.md](plan.md) | Execution plan, milestones, phases | approved |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius | approved |
| [user-stories.md](user-stories.md) | User stories & acceptance criteria | approved |
| [design.md](design.md) | Technical design & API contracts | approved |
| [data-model.md](data-model.md) | Storage schema changes (none) | approved |
| [test-plan.md](test-plan.md) | Test strategy & coverage matrix | approved |
| [rollout.md](rollout.md) | Rollout strategy, flags, rollback | approved |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-26 | Strict driver **allowlist** (not a denylist) | Most secure; GDAL dispatches by content sniffing, so an extension check is bypassable. Owner chose allowlist. |
| 2026-06-26 | In-process **deregistration** + `GDAL_SKIP` env (denylist) for subprocess/CLI | `GDAL_SKIP` only acts at registration and can't express an allowlist for the already-registered `osgeo.gdal`; deregistration is version-independent and covers in-process reads where the CVE would fire. |
| 2026-06-26 | Allowlist = raster {GTiff, COG, VRT, JPEG, PNG, MEM}, vector {GPKG, GeoJSON, Memory} | Confirmed by a full audit of every driver the imagery + training pipelines use. |
| 2026-06-26 | Full spec ceremony before coding | Owner choice; repo convention for feature/security work. |
