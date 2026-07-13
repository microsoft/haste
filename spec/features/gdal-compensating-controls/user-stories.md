# User Stories: GDAL Deferral Compensating Controls

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Uploads imagery / footprints and runs assessment | Uploads and processing succeed for valid files |
| Admin / Security Owner | Owns the GDAL dependency exception | The deferral is defensible; controls are enforced and reviewed |
| Attacker (negative persona) | Supplies a malicious file or URL | MUST be blocked before GDAL parses untrusted bytes |

---

## Stories

### US-001: Restrict GDAL to an allowlist of drivers

**As an** Admin/Security Owner,
**I want** GDAL/OGR to register only the drivers HASTE actually uses,
**So that** the vulnerable HDF4/HDF-EOS code path can never be reached from untrusted imagery.

**Priority:** P1
**Estimate:** M
**Component(s):** `hastelib/src/hastegeo/core/utils/gdal_security.py`, all parse sites

**Acceptance Criteria:**

```gherkin
Given the HASTE process has started and harden_gdal() has run
When code calls gdal.Open() / rasterio.open() / fiona.open() on an HDF4 (or HDF5/netCDF) file
Then GDAL has no driver registered for it and the open fails cleanly, never entering the HDF4/EOS parser
```

```gherkin
Given the driver allowlist is enforced
When the imagery pipeline reads/writes GTiff, COG, VRT, JPEG, GPKG, or GeoJSON
Then all operations succeed unchanged
```

**Notes:** In-process via driver deregistration; subprocess/CLI via `GDAL_SKIP` env.

---

### US-002: Strict size + type checks at the upload boundary

**As a** Disaster Analyst,
**I want** the chunked uploader to reject oversized or wrong-type files,
**So that** a hostile or accidental upload can't OOM the node or smuggle a malicious format into GDAL.

**Priority:** P1
**Estimate:** S
**Component(s):** `core/processors/uploader.py`, `api/hastefuncapi` (`UploadFileByChunk`)

**Acceptance Criteria:**

```gherkin
Given a chunked upload whose assembled size exceeds HASTE_MAX_UPLOAD_BYTES
When a chunk pushes the cumulative total over the cap
Then the upload is rejected with HTTP 400 and partial chunks are cleaned up
```

```gherkin
Given an upload declared as "tif" whose bytes are not a TIFF (e.g. HDF4 or zip magic)
When the upload is finalized
Then a magic-byte check fails and the file is rejected with HTTP 400 before GDAL parses it
```

**Notes:** Reuses the existing `_resolve_data_format` allowlist; adds size + content checks.

---

### US-003: SSRF / size hardening of the imagery downloader

**As an** Admin/Security Owner,
**I want** the remote imagery downloader to refuse cross-host redirects and cap download size,
**So that** an allowlisted source can't bounce the fetch to an internal host and oversized fetches can't exhaust the node.

**Priority:** P1
**Estimate:** S
**Component(s):** `core/utils/downloader.py`

**Acceptance Criteria:**

```gherkin
Given an allowlisted imagery URL that responds with a 302 to a different host
When download_imagery_from_urls fetches it
Then the redirect is not followed and the URL is skipped/refused and logged
```

```gherkin
Given a remote imagery response larger than HASTE_MAX_IMAGERY_DOWNLOAD_BYTES
When it is streamed
Then the download aborts and the partial file is discarded
```

**Notes:** Mirrors `prepare_imagery.py::_download_user_footprints_to`.

---

### US-004: Document controls + formalize weekly review

**As an** Admin/Security Owner,
**I want** the compensating controls and a weekly review cadence written down,
**So that** the GDAL exception is auditable and gets closed when a trusted wheel ships.

**Priority:** P2
**Estimate:** S
**Component(s):** `docs/known-vulnerabilities.md`, `docs/security-configuration.md`, `docs/triage-process.md`, `CHANGELOG.md`

**Acceptance Criteria:**

```gherkin
Given the controls are implemented
When a reviewer reads known-vulnerabilities.md Root Cause C
Then each control links to its enforcing code and the weekly-review cadence, owner, and exit criterion are stated
```

---

## Agent Assignment Map

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `gis` | Satellite imagery, GDAL/rasterio, provider adapters | Yes |
| `backend-dev` | Python backend, API, processors, data layers, Docker | Yes |
| `security` | CVE analysis, dependency audits | No (reports only) |
| `backend-validation` | Validates backend code against specs, tests | No (validates only) |
| `security-validation` | Validates security findings | No (validates only) |
| `orchestrator` | Tracks spec status | No (observes only) |

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `gis` (+ `backend-dev`) | `backend-validation` + `security-validation` | GDAL driver allowlist is imagery/GDAL domain |
| US-002 | `backend-dev` | `backend-validation` | Upload boundary in `processors`/`api` |
| US-003 | `backend-dev` (+ `gis`) | `backend-validation` | Download/SSRF; imagery domain overlap |
| US-004 | `backend-dev` | `security-validation` | Docs + process |

### Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Phase 1 — Core hardening module | `gis` | `backend-dev` | `backend-validation` |
| Phase 2 — Boundaries (upload/download) | `backend-dev` | `gis` | `backend-validation` |
| Phase 3 — Containers + docs | `backend-dev` | `security` | `security-validation` |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P1 | US-001 | Phase 1 | `gis` | `hastelib` |
| P1 | US-002 | Phase 2 | `backend-dev` | `hastelib`/`api` |
| P1 | US-003 | Phase 2 | `backend-dev` | `hastelib` |
| P2 | US-004 | Phase 3 | `backend-dev` | `docs` |

## Out of Scope

- [ ] Upgrading GDAL to 3.13 — blocked on a trusted pip wheel (this feature is the deferral's compensating controls, not the fix).
- [ ] Building/owning a custom GDAL wheel — separate effort.
- [ ] UI changes — none required.
