# Known Vulnerabilities

This document tracks Dependabot alerts that are deferred because they cannot be patched without breaking a dependency, and explains the constraints.

Update this file when upstream packages ship fixes or when the deployment model changes.

For the triage workflow, ownership, and SLAs that govern when entries land here, see [triage-process.md](triage-process.md).

---

## ~~Root Cause A — azurite → @azure/ms-rest-js (deprecated)~~ — RESOLVED

**Previously affected:** Dependabot alerts #3, #4, #6, #7, #9, #10, #11, #20, #21, #22, #23, #24, #25, #26, #27, #28, #29 (`package-lock.json`)

**Resolution:** `azurite` was removed from `package.json` and `package-lock.json` regenerated. It no longer appears in the project's dependency tree, so these alerts no longer surface in `npm audit` or Dependabot scans. Azurite is now installed globally by developers (`npm install -g azurite`). See [development.md](development.md#local-storage-emulator-azurite) for usage guidance.

---

## Root Cause B — npm bundled dependencies

**Affects:** Dependabot alerts #14, #15, #16, #32 (`ui/package-lock.json`)

`npm` bundles copies of certain packages inside its tarball (`inBundle: true`). These cannot be reached by npm `overrides` — the only fix is upgrading `npm` itself to a version that ships the patched bundled copy.

- **Alerts #14, #15, #16** — `picomatch` and `brace-expansion` were unpatched inside `npm@11.12.1`; upgrading to `npm@11.13.0` (already done) ships the fixed versions inside the bundle. These alerts should auto-close on the next Dependabot rescan; dismiss as fixed if they persist.
- **Alert #32** — `ip-address@10.1.0` (CVE-2026-42338, GHSA-v2v4-37r5-5v8g, Medium) is bundled inside `npm@11.13.0` via `socks`. Patched version is `10.1.1`. Blocked on `npm` shipping a release that bundles `ip-address@10.1.1`. The XSS in `Address6` HTML-emitting methods is not reachable from any application code path — `npm` does not render IP addresses as HTML at runtime.

| Alert # | Package | CVE | Advisory | Severity | Status |
|---------|---------|-----|----------|----------|--------|
| #14 | picomatch | CVE-2026-33671 | GHSA-c2c7-rcm5-vvqj | High | Fixed in npm@11.13.0 |
| #15 | picomatch | CVE-2026-33672 | GHSA-3v7f-55p6-f55p | Moderate | Fixed in npm@11.13.0 |
| #16 | brace-expansion | CVE-2026-33750 | GHSA-f886-m6hf-6m8v | High | Fixed in npm@11.13.0 |
| #32 | ip-address | CVE-2026-42338 | GHSA-v2v4-37r5-5v8g | Medium | Blocked on npm upstream |

---

## Root Cause C — GDAL wheel availability gap

**Affects:** Dependabot alerts `#33`, `#34`, `#38` (`hastelib/pyproject.toml`, `api/hastefuncapi/requirements.txt`, `api/hastefuncqueues/requirements.txt`, `docker/imageryprep/requirements.txt`)

HASTE runtime depends on `GDAL==3.9.2` via externally hosted pip wheels in API and imageryprep requirements files. Dependabot advisory metadata points to patched versions in the 3.13 line, but no trusted, prebuilt pip wheel source is currently available for HASTE's Linux runtime constraints.

The current decision is to defer upgrade and apply compensating controls until a trusted upstream wheel source is available or the deployment model is changed.

### Compensating controls (implemented)

These controls are enforced in code — see
[`spec/features/gdal-compensating-controls/`](../spec/features/gdal-compensating-controls/)
and [ADR-0004](../spec/architecture/decisions/0004-gdal-driver-allowlist.md).

- **Authenticated, allowlisted providers/endpoints.** User-supplied imagery
  and footprint URLs are validated against an allowlist
  (`hastelib/src/hastegeo/core/utils/url_allowlist.py`); `PutLayer` rejects
  off-allowlist hosts at submission time.
- **Reject unsupported formats before GDAL parsing (incl. HDF4/EOS).** GDAL/OGR
  is restricted at process startup to an allowlist of the drivers HASTE
  actually uses (raster `GTiff, COG, VRT, JPEG, PNG, MEM`; vector
  `GPKG, GeoJSON, Memory`) by deregistering every other driver
  (`hastelib/src/hastegeo/core/utils/gdal_security.py::harden_gdal`, wired into
  every parse site). The HDF4/HDF4Image/HDF5/HDF5Image/netCDF families are
  additionally refused via `GDAL_SKIP` in the imageryprep and training
  Dockerfiles, covering subprocess GDAL CLI tools.
- **Strict size and type checks at upload and download boundaries.** The
  chunked uploader enforces a cumulative size cap and a magic-byte check that
  the assembled file matches its declared format before it reaches GDAL
  (`core/processors/uploader.py`, `gdal_security.sniff_file_type`). The imagery
  downloader caps download size and (for blob/S3) checks object size first
  (`core/utils/downloader.py`). Limits are env-tunable
  (`HASTE_MAX_UPLOAD_BYTES`, `HASTE_MAX_IMAGERY_DOWNLOAD_BYTES`).
- **SSRF / cross-host redirect guards.** Both the imagery downloader and the
  user-footprint fetch (`workflows/prepare_imagery.py`) refuse to follow
  redirects, so an allowlisted source cannot bounce a server-side fetch to an
  internal host.
- **Weekly exception review.** Tracked per
  [triage-process.md](triage-process.md#weekly-dependency-exception-review);
  closes when a trusted GDAL 3.13+ wheel or a deployment-model change lands.

| Alert # | Package | CVE | Advisory | Dependabot state | Current disposition |
|---------|---------|-----|----------|------------------|---------------------|
| `#33` | GDAL | CVE-2026-8088 | GHSA-j3f5-rw74-g4rv | Dismissed (risk tolerable) | Deferred with compensating controls |
| `#34` | GDAL | CVE-2026-8087 | GHSA-h9rh-5ffh-h669 | Dismissed (risk tolerable) | Deferred with compensating controls |
| `#38` | GDAL | CVE-2026-8212 | GHSA-r5m4-5vww-w9f5 | Dismissed (risk tolerable) | Deferred with compensating controls |

---

## Dismissal rationale (for GitHub Dependabot)

When dismissing these alerts on GitHub, use **"Risk tolerable for this project"** with notes along these lines:

- **Alerts #3, #4, #6, #7, #9, #10, #11, #20–29:** Resolved — `azurite` removed from `package.json` and `package-lock.json` regenerated. These alerts should auto-close on next Dependabot rescan; dismiss as fixed if they persist.
- **Alerts #14, #15, #16:** `inBundle: true` inside `npm@11.13.0` tarball; non-bundled installs already at patched versions. No production exposure.
- **Alert #32:** `ip-address` `inBundle: true` inside `npm@11.13.0` tarball. XSS in `Address6` HTML-emitting methods; not reachable from application code. Blocked on npm upstream shipping `ip-address@10.1.1` in its bundle.
- **Alerts `#33`, `#34`, `#38`:** Patched versions require GDAL 3.13 runtime artifacts that are not currently available as trusted pip wheels for this deployment model. Runtime is constrained to externally hosted Linux wheels. Compensating controls are in place or in progress: allowlisted providers/endpoints, pre-parse format filtering, strict size/type checks, and SSRF/redirect guards. Review weekly; close when a trusted wheel source or alternate deployment model is ready.
