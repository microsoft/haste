# User Stories: GDAL 3.13 Native Runtime

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Platform Operator | Deploys and runs HASTE environments | Know exactly which GDAL runs where, and deploy the same artifact everywhere |
| Security Reviewer | Verifies HASTE's dependency and configuration posture | Evidence for versions, drivers and configuration, from inside the running service |
| Disaster Analyst | Uses HASTE to assess damage from imagery | Imagery preparation, labeling and tiles keep working |

---

## Stories

### US-001: Reproducible GDAL runtime

**As a** Security Reviewer,
**I want** GDAL and its native dependencies built in CI from pinned, verified sources,
**So that** I can review exactly what HASTE ships.

**Priority:** P0
**Component(s):** `native/gdal-runtime/`, `.github/workflows/`

**Acceptance Criteria:**

```gherkin
Given the runtime source lock
When the build workflow runs
Then every downloaded tarball and source distribution matches its pinned SHA-256
And the run publishes the wheels, the manifest, an SBOM, license notices and a provenance attestation
```

```gherkin
Given a source file whose hash does not match the lock
When the build runs
Then the build fails before compiling anything
```

### US-002: One libgdal per process

**As a** Security Reviewer,
**I want** every GDAL-linked binding to use the same native runtime,
**So that** version and driver checks describe the whole process.

**Priority:** P0
**Component(s):** `native/gdal-runtime/`

**Acceptance Criteria:**

```gherkin
Given a process that imports GDAL, rasterio, fiona, pyogrio and pyproj
When the runtime report is collected
Then exactly one libgdal and one libproj are mapped
And every binding reports GDAL 3.13.3
```

### US-003: Fail-closed runtime self-check

**As a** Platform Operator,
**I want** each service to refuse to start when its GDAL runtime differs from the approved one,
**So that** a wrong or weakened runtime never serves traffic.

**Priority:** P0
**Component(s):** `native/gdal-runtime/`, `hastelib`, `api/titilerfuncapi/`, Batch images

**Acceptance Criteria:**

```gherkin
Given the approved runtime and the default configuration
When the service starts
Then the self-check passes and logs the runtime report
```

```gherkin
Given GDAL_VRT_ENABLE_PYTHON=YES, or GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE=ALL, or a GDAL_DRIVER_PATH other than "disable"
When the service starts
Then the self-check fails and the service does not start
```

```gherkin
Given a VRT document that uses a raw band or a Python pixel function
When the self-check probes it
Then GDAL refuses to open or read it
```

### US-004: Untrusted inputs never reach the VRT driver

**As a** Security Reviewer,
**I want** downloaded and uploaded files opened only with an explicit driver allowlist,
**So that** a VRT document disguised as imagery is rejected.

**Priority:** P0
**Component(s):** `hastelib/src/hastegeo/core/utils/`

**Acceptance Criteria:**

```gherkin
Given a downloaded "imagery" file whose content is a VRT document
When imagery preparation processes it
Then it is rejected before GDAL parses it, and the layer fails with a clear error
```

```gherkin
Given a valid Cloud Optimized GeoTIFF
When imagery preparation processes it
Then the output COG and JPEG preview match those produced by the current release
```

### US-005: Tile server on the approved runtime

**As a** Disaster Analyst,
**I want** imagery tiles to keep rendering,
**So that** labeling and results views work on the hardened tile server.

**Priority:** P0
**Component(s):** `api/titilerfuncapi/`

**Acceptance Criteria:**

```gherkin
Given a project with pre- and post-event imagery
When the map requests tiles through APIM
Then tiles render, including reprojected sources
```

```gherkin
Given a tile request whose source is inline VRT, vrt://, a remote VRT document, or a /vsi path
When TiTiler handles it
Then no VRT is opened and the request fails
```

### US-006: One immutable artifact per deployment

**As a** Platform Operator,
**I want** Function Apps deployed from a package built once,
**So that** dev and prod run the same bytes.

**Priority:** P0
**Component(s):** `.github/scripts/deploy_apps.sh`, `.github/workflows/deploy-apps.yml`, `azure.yaml`

**Acceptance Criteria:**

```gherkin
Given a deployment run
When a Function App is deployed
Then its package was built once from hash-locked requirements, recorded by SHA-256, and published without a remote build
And the app is tagged with that SHA-256
```

### US-007: No deployment can relax the GDAL hardening

**As a** Security Reviewer,
**I want** CI to reject any configuration that weakens the GDAL settings,
**So that** the hardening holds across redeployments.

**Priority:** P1
**Component(s):** `.github/scripts/tests/`, `hastelib/tests/build/`

**Acceptance Criteria:**

```gherkin
Given a change that sets a forbidden GDAL option in infrastructure, scripts, Dockerfiles or app settings
When CI runs
Then the guard test fails and names the file and the option
```

---

## Agent Assignment Map

| Story | Implementing Agent | Validating Agent | Notes |
|---|---|---|---|
| US-001 | `backend-dev` + `gis` | `backend-validation` | New native dependencies: `security` audits, `security-validation` confirms |
| US-002 | `gis` | `backend-validation` | |
| US-003 | `backend-dev` | `backend-validation` | |
| US-004 | `gis` | `backend-validation` | |
| US-005 | `backend-dev` | `backend-validation` | Coordinate with the TiTiler route-surface work |
| US-006 | `backend-dev` | `backend-validation` | |
| US-007 | `backend-dev` | `backend-validation` | |
