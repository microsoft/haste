# Changelog

All notable changes to HASTE are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows the Docker image tags defined in the CI workflows (see [.github/workflows/](.github/workflows/)).

---

## [Unreleased]

### Added
- **Shared multi-tenant GPU Batch pools** — For deployments running many environments against scarce GPU quota, HASTE can now share a small set of multi-tenant Batch pools (H100 for training, T4 for inference/imageryprep + spillover) instead of one pool per environment. Data isolation is enforced at the credential boundary: each job mints a short-lived **user-delegation SAS** scoped to its own storage container (the pool identity is used only for ACR pull and holds no storage access), so a tenant's task can never read another tenant's data. Pools autoscale on low-priority nodes and scale to zero when idle. New `hastelib` routing picks a pool from an ordered candidate list **at submit time** (first with an idle node, else the preferred pool). Provisioned by the standalone [`infra/shared-pools.bicep`](infra/shared-pools.bicep) + [`shared-pools.bicepparam`](infra/shared-pools.bicepparam); opted into per environment via `AZURE_BATCH_*_POOL_IDS`, `AZURE_BATCH_USE_SAS`, and `AZURE_BATCH_MANAGE_POOLS` (all default to the legacy single-pool behavior). Full design in [`spec/features/batch-compute-expansion/`](spec/features/batch-compute-expansion). See [docs/configuration.md](docs/configuration.md#shared-multi-tenant-gpu-pools).

### Changed
- **`infra/modules/batchPool.bicep` parameterized** — one module now serves fixed-dedicated (dev/prod) and autoscale-low-priority (shared) pools via `scaleMode` / `nodeType` / `minNodes` params, with optional VNet injection. Backward-compatible defaults.
- **Generic-default IaC for reuse by other partners** — `HASTE_RESOURCE_PREFIX` now defaults to the neutral `haste` (overridable per deployment); the shared-pools template keeps its account/ACR as bring-your-own params. The `api`/`queues` Function App identity is granted **Storage Blob Delegator** (in `functionApp.bicep`) so it can mint user-delegation SAS.
- **Pinned `azure-batch==14.2.0`** — the 15.x track-2 rewrite restructures the batch models this code uses; migration is tracked separately.

---

## [v2.0.0] — Building labeling workflow & one-step `azd` setup

### Added
- **Building labeling workflow (embeddings + interactive labeler)** — A second image-layer workflow, selectable alongside the existing Standard workflow on the create/edit Image Layer screen. Building layers expose an **Embed** button that runs a new embedding job (torchgeo RCF MOSAIKS features around each footprint, generating PMTiles + a footprints-with-features GeoJSON), then an **Interactive Label** tool (`/interactive-label/...`) where reviewers click or **Ctrl+drag box-select** to label buildings Intact/Damaged/Cloudy while an in-browser logistic-regression model predicts damage for every building and reports k-fold CV precision/recall/F1. Saved labels + per-building predictions feed the existing Validation and Assessment reports unchanged. The embedding job reuses the training Docker image (adds tippecanoe + an `embed-buildings` CLI shim); predictions are written in footprint row order so the reports join by row index. ([#42](https://github.com/microsoft/haste/pull/42))
- **One-step infrastructure setup (`azd up`)** — Infrastructure is now declarative Bicep in `infra/` orchestrated by the Azure Developer CLI: `azd up` provisions every resource and deploys the three Function Apps and the Static Web App cross-platform, replacing the bash setup scripts. Post-deploy PowerShell hooks publish the UI, sync APIM operations and inject the Function host key, seed admin settings, and bootstrap the first admin. A `preprovision` hook makes the immutable Batch-pool image tags transparent when reusing a shared pool. Configuration modes (Batch create-vs-BYO, email sender domain, Front Door, development mode, `HASTE_FIRST_ADMIN_EMAIL`) are documented in [docs/configuration.md](docs/configuration.md). ([#74](https://github.com/microsoft/haste/pull/74))
- **Auto-expand first populated image layer** — When no image layer is selected, the project view now automatically expands the first image layer that contains models, reducing clicks to reach the training workflow. ([#72](https://github.com/microsoft/haste/pull/72))
- **`QUICKSTART.md` local-stack runbook** — A phased, verify-gated quickstart for standing up the local dev stack, written for both humans and AI coding agents (platform-specific guidance, health checks, troubleshooting, lifecycle management); `README.md` gains a banner and a Quick Start section, and `AGENTS.md` references it as the agent runbook. ([#76](https://github.com/microsoft/haste/pull/76))

### Changed
- **`hastegeo` bumped to 1.0.26** — Library version propagated across all `requirements.txt` files and `__about__.py`.
- **Blob storage is now the source of truth for `hastegeo` versioning** — The `hatch` build hook lists the published `hastegeo-*` wheels, takes the highest version, and increments from there (writing the resolved version back into `__about__.py`), so a build can never collide with or overwrite an already-published wheel. Adds `HASTE_BUMP=major|minor|patch` and `HASTE_SET_VERSION=X.Y.Z` for intentional releases; falls back to the committed `__about__.py` version when blob listing is unavailable. ([#71](https://github.com/microsoft/haste/pull/71))
- **APIM endpoint sync on deploy** — `deploy_apps.sh` now detects the HTTP endpoints exposed by the deployed `hastefuncapi` (via `az functionapp function list`) and idempotently creates a matching APIM operation + `set-backend-service` policy for any that don't already exist, so newly added `@app.route` handlers stop silently 404/401-ing through APIM because they were never registered. Non-fatal when APIM/the base API isn't provisioned. ([#52](https://github.com/microsoft/haste/pull/52))
- **Configurable app footer** — `VITE_SHOW_FOOTER` is now driven from a GitHub Environment variable (defaults to `false`), baked into the Vite bundle at build time. ([#52](https://github.com/microsoft/haste/pull/52))
- **Unified back-button UX** — The plain HTML back button in the Interactive Labeler is replaced with a FluentUI `ActionButton`, consistent with the labeling tool and visualizer; `eventTypes` is threaded `LayerRow → ImageLayerInfoMobile → CreateEditModelTrainingModal`, removing a redundant `GetProjectDetails` call. ([#72](https://github.com/microsoft/haste/pull/72))
- **Mobile parity for embedding-workflow layers** — The narrow Layer Tools panel now matches the desktop row: building-workflow layers render an **Embed** button (instead of the wrong Launch Labeling Tool), a **Launch Validation Tool** button is exposed for all layer types, and tool buttons stretch full-width. ([#80](https://github.com/microsoft/haste/pull/80))
- **Transparent fill for unlabeled buildings** — In the Interactive Labeler, unlabeled buildings now render with a fully transparent fill (outline only) so the underlying imagery stays visible; labeled/predicted buildings keep the 0.5 translucent class color. ([#79](https://github.com/microsoft/haste/pull/79))

### Fixed
- **Videos missing from the published user docs** — The GitHub Pages docs build checked out without Git LFS, so Jupyter Book served 132-byte LFS pointer files instead of the `.mp4` videos. Added `lfs: true` to the docs checkout, fixing all 7 usage videos. ([#84](https://github.com/microsoft/haste/pull/84))
- **APIM route-template parameter mismatch** — Fixed a route-template bug (inherited from `setup_infra.sh`) where the declared APIM parameter name didn't match the `{param}` placeholder in the url-template (e.g. the CORS `options/{*path}` handler). ([#52](https://github.com/microsoft/haste/pull/52))

### Removed
- **Legacy bash infra scripts** — `setup/setup_infra.sh` and `setup/deploy_apps.sh` are retired in favor of the `azd` workflow above; `setup/README.md` and `docs/deployment.md` are rewritten accordingly. ([#74](https://github.com/microsoft/haste/pull/74))
- **Dead Azure Pipelines config** — Deleted the unused `azure-pipelines.yml` (it triggered on a `master` branch that isn't the default); CI/CD is GitHub Actions. ([#77](https://github.com/microsoft/haste/pull/77))

### Security
- **GDAL deferral compensating controls (CVE-2026-8087/8088/8212)** — GDAL `3.9.2` can't be upgraded to the patched 3.13 line (no trusted pip wheel), so the three memory-safety CVEs — worst a heap overflow in the HDF4/HDF-EOS driver — are deferred with controls enforced in code. New `hastegeo.core.utils.gdal_security.harden_gdal()` restricts GDAL/OGR to an allowlist of the drivers HASTE uses (raster `GTiff/COG/VRT/JPEG/PNG/MEM`, vector `GPKG/GeoJSON/Memory`), deregistering HDF4/HDF5/netCDF so a malicious file can't reach the vulnerable parser; `GDAL_SKIP` is set in the imageryprep/training images for subprocess GDAL tools. Added strict size + magic-byte type checks at the upload boundary, and size caps + cross-host-redirect refusal (SSRF guard) on the imagery downloader. Spec: `spec/features/gdal-compensating-controls/` + [ADR-0004](spec/architecture/decisions/0004-gdal-driver-allowlist.md). ([#65](https://github.com/microsoft/haste/pull/65), [known-vulnerabilities.md](docs/known-vulnerabilities.md) Root Cause C)
- **`pyarrow` upgraded 18.1.0 → 23.0.1 in the training env (CVE-2026-25087, High)** — Patches the same use-after-free in pyarrow's IPC file reader as the imageryprep fix, this time in `docker/training/env/env.yml` (the Azure Batch GPU training image). The bump was blocked by `deltalake==0.25.4`, which hard-caps `pyarrow<19`; since `deltalake` is pinned but never imported anywhere in the repo, it was upgraded to `deltalake==1.6.1` (1.x makes `pyarrow` an optional extra, decoupling it from the pin). ([#61](https://github.com/microsoft/haste/pull/61), [#60](https://github.com/microsoft/haste/issues/60))
- **`pyarrow` upgraded 18.1.0 → 23.0.1 (CVE-2026-25087, High)** — Patches a use-after-free in pyarrow's IPC file reader (triggered with pre-buffering enabled) where a crafted Arrow/Parquet file could corrupt memory and potentially execute code inside the **imageryprep** Azure Batch node, exposing its Managed Service Identity token (Blob / Data Lake read+write). Bumped the pin in `docker/imageryprep/requirements.txt` (`pyarrow==23.0.1`) and raised the floor to `pyarrow>=23.0.1` in `hastelib/pyproject.toml`, which also lifts the API containers once a new `hastegeo` wheel is published. ([#59](https://github.com/microsoft/haste/pull/59), [#57](https://github.com/microsoft/haste/issues/57))
- **npm Dependabot triage (16 of 19 alerts)** — Resolved 16 open Dependabot alerts via version bumps and dependency overrides: `vite` (CVE-2026-53571 fs.deny bypass), `js-yaml` (CVE-2026-53550 DoS), `react-router-dom` (CVE-2026-40181), and overrides for `shell-quote`, `undici`, `form-data`, `launch-editor`, `tar`, `joi`, and `@babel/core`. ([#56](https://github.com/microsoft/haste/pull/56))
- **Removed `npm`/`install` from UI dependencies** — Dropped two packages incorrectly listed as production dependencies of `ui/package.json`, eliminating 142 unnecessary transitive packages and resolving 6 Dependabot alerts (`undici`, `tar`, `brace-expansion`); added `react`/`react-dom` as explicit direct dependencies. ([#64](https://github.com/microsoft/haste/pull/64))

### Documentation
- **Workflow-first user guide** — Overhauled the GitHub Pages (Jupyter Book) docs to be goal-oriented: a new **Rapid Building Assessment** guide (the embeddings + Interactive Labeler flow), a new **Damage Mapping** guide (the standard segmentation flow), and a shared **Building Blocks** tier. Corrected Architecture/API pages against the current source (41 HTTP routes, environment-dependent auth, `hastegeo` v1.0.25 package, LocalRunner + Azure Batch runners), replaced stale "Azure Pipelines" descriptions with the real GitHub Actions scanning, split setup into `local-dev.md` and the infra team's `deployment.md`/`configuration.md`, and wired workflow screenshots throughout. ([#77](https://github.com/microsoft/haste/pull/77))
- **GDAL mitigation documented** — Recorded the disposition for the three GDAL memory-safety alerts (#33/#34/#38) as a deferred dependency exception with compensating controls (rather than a custom wheel rebuild) in `docs/known-vulnerabilities.md` and the triage report. ([#63](https://github.com/microsoft/haste/pull/63))
- **Open-source readiness cleanup** — Swept the `hastegeo` package rename through the docs autodoc pages (fixing the empty API reference), corrected route/queue counts and Docker ports against the live code, removed employee names/aliases in favor of role-based wording, populated `CODEOWNERS`, and fixed dead links/anchors across the docs and specs. ([#83](https://github.com/microsoft/haste/pull/83))
- **README polish** — Grouped the Documentation links by purpose and fixed dead/mangled links ([#82](https://github.com/microsoft/haste/pull/82)); added a "See it in action" animated demo section ([#78](https://github.com/microsoft/haste/pull/78)); pointed the Image Layers sources at Planet's open disaster data ([#85](https://github.com/microsoft/haste/pull/85)).

---

## [v1.4.7] — Hotfix: non-admin project creation

### Fixed
- **Non-administrator users couldn't open the Create Project modal** — `createComponentDefaultState` made a `GetAdminSettings` call whose result was never used (the function reads `staticSettings` from local JSON instead). That dead call returned HTTP 403 for non-admin users, blocking the modal from opening. Removed the unused call. ([#53](https://github.com/microsoft/haste/pull/53))

---

## [v1.4.6] — Building validation & assessment, custom footprints

### Added
- **Building Validation workflow** — New `/validation/:projectId/:imageLayerId` page where reviewers walk a random sample of building footprints over the post-disaster imagery and label each **Damaged / Not Damaged / Unknown** (keyboard shortcuts `1`/`2`/`3`), saved to `data/{projectId}/validation/{imageLayerId}.json`. A new `LayerRow` column launches the tool and shows a labeled-count badge. ([#25](https://github.com/microsoft/haste/pull/25))
- **Validation & Assessment reports** — Two new items in the model **Results** dropdown: a *Validation Report* (overall accuracy, macro F1, per-class precision/recall/F1, confusion matrix; `Unknown` labels excluded from metrics) and an *Assessment Report* (per-building predictions summary, precision/recall/F1/AP at a configurable threshold, a precision-recall curve, and a finite-population estimate with 95% CI of total damaged buildings). The assessment modal degrades gracefully when no validation labels exist. ([#25](https://github.com/microsoft/haste/pull/25))
- **New API endpoints** — `GetBuildingFootprintsGeoJSON`, `GetBuildingValidation`, `PutBuildingValidation`, `GetValidationReport`, and `GetAssessmentReport`; `GetProjectDetails` now returns `validationLabelCount` per image layer so the dashboard can gate reporting buttons without an extra round-trip. ([#25](https://github.com/microsoft/haste/pull/25))
- **Raw predictions overlay** in the Visualizer. ([#25](https://github.com/microsoft/haste/pull/25))
- **Custom building footprints** — Optional panel on the Create Image Layer page to supply a building-footprints GeoPackage (URL or `.gpkg` upload) instead of the Overture Maps download. The imageryprep workflow downloads, reprojects to EPSG:4326, and clips it to the post-event AOI before writing the same `building_footprints_<project>_<layer>.gpkg` path the pipeline already expects — downstream inference/visualization need no changes. Adds `ImageLayer.userBuildingFootprintsUrl`, a `GPKG` data format, and an `{tif, gpkg}` allowlist on chunked upload. ([#38](https://github.com/microsoft/haste/pull/38))
- **Feature-flagged `AppFooter` component**, hidden by default and enabled via `VITE_SHOW_FOOTER=true`. ([#40](https://github.com/microsoft/haste/pull/40))

### Changed
- **`hastegeo` bumped to 1.0.15** — Library version propagated across all `requirements.txt` files and `__about__.py`
- `ImageLayer` URL validators moved into `hastegeo` for reuse across API and workflows. ([#38](https://github.com/microsoft/haste/pull/38))

### Fixed
- **Visualizer was unreachable** — `GetVisualizerResults` rejected every real `modelId` with HTTP 400 because PR #18's hardening validated it as a GUID, but model IDs are 4-digit short integers. Added a `^[0-9]{1,8}$` validator for the `modelId` param while keeping the GUID checks on `projectId`/`imageLayerId`. ([#39](https://github.com/microsoft/haste/pull/39))
- **"Don't show again" on guided tours now persists** across reloads and browser restarts — fixed three compounding bugs in the guided-tour state logic and moved the per-tour flag from `sessionStorage` to `localStorage`. ([#37](https://github.com/microsoft/haste/pull/37))
- **Validation report matched no labels when the user GPKG had integer IDs** — label matching now coerces IDs consistently. ([#38](https://github.com/microsoft/haste/pull/38))
- **Valid-area mask** is now also saved on the user-footprints path, matching the Overture path. ([#38](https://github.com/microsoft/haste/pull/38))
- **Permission-denied on chunked file upload** in the local dev compose stack. ([#38](https://github.com/microsoft/haste/pull/38))

### Security
- **Additional SDL hardening (UI)** — Added a `globalHeaders` block to `staticwebapp.config.json` (CSP, HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`); repointed the swipe-map script from `samples.azuremaps.com` to a vendored local copy so CSP can constrain all script sources; new `sanitizeRedirectPath()` collapses the logout target to a same-origin relative path (open-redirect guard); new `safeHref()` blocks `javascript:`/`data:`/`vbscript:`/protocol-relative URLs and adds `rel="noopener noreferrer"` at all `<Link>` sites; vendored `world.geojson` locally to drop an external GitHub fetch. ([#41](https://github.com/microsoft/haste/pull/41))
- **Custom-footprint download hardening** — `validate_footprint_url` extends the imagery allowlist with an exact match against `BLOB_ACCOUNT_URL`; the loopback-host fallback is opt-in only via `HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS=1` (never on by default) to avoid acting as an SSRF gadget. The workflow re-validates the URL (defense in depth), caps the download size (default 500 MB, env-tunable), refuses cross-host redirects, and soft-fails so already-produced COGs still upload. ([#38](https://github.com/microsoft/haste/pull/38))

### Documentation
- **Agentic spec framework** — Added the HASTE specification framework under `spec/` (feature templates, architecture docs, ADR template) plus the specialized agent team configuration in `.github/agents/`, `.github/copilot-instructions.md`, `.github/instructions/`, `.github/prompts/`, and `.github/skills/`. ([#36](https://github.com/microsoft/haste/pull/36))
- **Function API & Queue Functions READMEs** — Rewrote `api/hastefuncapi/README.md` and `api/hastefuncqueues/README.MD` with architecture overviews, a categorized table of all REST endpoints, per-queue-function lifecycle descriptions, and clearer setup, authentication, error-handling, and deployment guidance. ([#48](https://github.com/microsoft/haste/pull/48))

---

## [v1.4.5] — Per-environment deploy configuration

### Changed
- **`deploy-apps.yml` now drives per-target config from GitHub Environments** instead of workflow_dispatch inputs. The dispatch form collapses to 5 fields (environment, component, training/imageprep/app tags); all environment-specific values live as environment-scoped secrets. **Operators forking this repo must create a GitHub Environment per deployment target and populate the secrets documented in [`.github/workflows/README.md`](.github/workflows/README.md) before running the workflow.** ([#28](https://github.com/microsoft/haste/pull/28))
- **`ENVIRONMENT_TYPE` is now a per-environment secret** rather than implicitly the GitHub Environment name, decoupling the application's runtime environment type (`dev`/`staging`/`prod`) from operator-chosen environment labels. ([#28](https://github.com/microsoft/haste/pull/28))
- **Selective component deploy** — the dispatch form has a `component` dropdown (`funcapi` / `funcqueue` / `titiler` / `swa` / `all`) so operators can redeploy a single component without rebuilding and redeploying the rest. ([#28](https://github.com/microsoft/haste/pull/28))
- **`hastegeo` bumped to 1.0.5** — Library version propagated across all `requirements.txt` files and `__about__.py` ([#35](https://github.com/microsoft/haste/pull/35))

### Fixed
- **Azure Batch tasks failed to start** — imageryprep/training container tasks now run as `--user 0:0` so they can write to the root-owned Batch task working directory (`/mnt/batch/tasks`), which the image's non-root `appuser` could not access ([#35](https://github.com/microsoft/haste/pull/35))

### Security
- **Fully-isolated deploy blueprint** — All target-specific secrets are now defined at GitHub Environment scope (`AZURE_CLIENT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME`, `BATCH_ACCOUNT`, `SHARED_RESOURCE_GROUP`, and all resource-naming/domain values); only `AZURE_TENANT_ID` remains at repository scope. The recommended posture is that each deployment target is backed by its own subscription, service principal, container registry, batch account, and resource groups, so a compromised workflow run for one environment cannot reach another environment's credentials or resources. Operators sharing specific infrastructure across environments may move just those secrets to repository scope; the workflow honors environment-first lookup precedence and the YAML works either way. ([#28](https://github.com/microsoft/haste/pull/28))

---

## [v1.4.4] — Cached building footprints and local Docker dev fixes

### Added
- Cache building footprints per image layer in the imageryprep workflow instead of re-downloading on every inference run; image layers created before this change must be re-processed ([#24](https://github.com/microsoft/haste/pull/24))
- "Download Building Footprints" menu item in the image-layer UI dropdown ([#24](https://github.com/microsoft/haste/pull/24))
- `HASTE_SKIP_VERSION_BUMP` now honored in the hastelib Hatchling `finalize()` hook so pip-driven builds (Dockerfiles, CI) can opt out of the version bump and wheel upload ([#19](https://github.com/microsoft/haste/pull/19))

### Changed
- Bump `hastegeo` to 1.0.4
- Bump UI base image to `azurelinux/base/nodejs:24` for Vite 8 compatibility ([#19](https://github.com/microsoft/haste/pull/19))
- Isolate the Overture Maps footprint download in a subprocess with a configurable timeout so `pyarrow` SIGSEGVs and upstream hangs no longer take down completed mosaics/COGs ([#24](https://github.com/microsoft/haste/pull/24))
- Surface footprint-download failures to the UI via `FAILED` image-layer status with a captured cause ([#24](https://github.com/microsoft/haste/pull/24))

### Fixed
- Unblock local `docker compose` dev build — Dockerfile paths, CLI shim modules, and GPU env-var override after the `hasteutils`→`hastelib` / `haste`→`hastegeo` rename ([#19](https://github.com/microsoft/haste/pull/19), closes [#21](https://github.com/microsoft/haste/issues/21))
- Labeling tool works without an Azure Maps subscription in local dev ([#23](https://github.com/microsoft/haste/pull/23))
- Use `--bbox=VALUE` form so argparse parses negative-longitude AOIs ([#24](https://github.com/microsoft/haste/pull/24))
- Fix stale `haste`/`haste_geo` references in repo-root and `docker/README.md` ([#26](https://github.com/microsoft/haste/pull/26))

---

## [v1.4.3] — Secure configuration and SDL hardening

### Added
- **Secure configuration guide** — New `docs/security-configuration.md` for customers deploying HASTE in their own subscription: authentication and authorization, secrets and key management, network and transport configuration (CORS, CSP, TLS), container hardening, logging and incident response, known limitations with operational mitigations, and a pre-production checklist
- **Venv-based local-dev launcher** — `.vscode/launch-funcapp.ps1` runs the Functions host inside each folder's `.venv` and reinstalls dependencies only when `requirements.txt` has changed (SHA256 marker); new `venv func: host start` tasks in `tasks.json`

### Changed
- **Azurite global install** — Removed `azurite` from `package.json`; developers now install it globally (`npm install -g azurite`). This resolves Dependabot alerts #3, #4, #6, #7, #9, #10, #11, which were blocked by `azurite → @azure/ms-rest-js` transitive vulnerabilities.
- **`hastegeo` bumped to 1.0.2** — Library version propagated across all `requirements.txt` files and `__about__.py`
- **GDAL platform-scoped** — Linux-only GDAL wheel now pinned with `sys_platform == 'linux'` marker so Windows venvs install cleanly
- **IPv4 for local dev** — SWA emulator (`swa: start` task) and the UI's `tileServerSettings` now use `127.0.0.1` instead of `localhost` to avoid IPv6 resolution hangs on Windows
- **Removed `@turf/turf`** — Dropped UI dependency for license compatibility

### Security
- **Imagery URL allowlist (SSRF mitigation)** — `PutLayer` rejects imagery URLs whose host is not under `*.blob.core.windows.net` or `*.amazonaws.com`; the UI mirrors this client-side for inline feedback when adding a URL; the imagery downloader applies the same allowlist as defense-in-depth at fetch time. Closes the application-layer SSRF gap previously documented as a known limitation
- **Strict parameter validation on API endpoints** — `GetProjectDetails`, `DeleteProject`, `DeleteLayer`, `DeleteUser`, and `GetVisualizerResults` now validate GUID and email request parameters against allowlist regexes and return generic HTTP 400 for malformed input
- **Path-traversal guard for blob URLs** — `LocalRunner` rejects blob URLs containing `..` segments or null bytes before composing a blob name
- **Error message sanitization** — Raw exception messages, pydantic validation details, and batch task `stderr.txt` content no longer surface to API clients or the UI; full content is still logged server-side for admin diagnostics
- **Narrowed exception handling** — `except Exception: pass` clauses in `function_app.py` (base64 principal decode), `docker_utils.py` (container cleanup), and `local.py` (blob client construction, chmod, partial-download cleanup) replaced with specific exception types and debug logging

---

## [v1.4.2] — Security and pipeline hardening

### Added
- **CodeQL scanning** — Static analysis workflow covering Python, JavaScript/TypeScript, and GitHub Actions, running on PRs and a weekly schedule

### Changed
- **Docker build CI** — Training and imagery-prep images now only rebuild when relevant paths change (`docker/training/`, `docker/imageryprep/`, `hastelib/`), reducing CI time for UI-only changes
- **GitHub Actions permissions** — Explicit least-privilege `permissions` blocks added to all workflows

### Fixed
- Minor UI API utility cleanup
- **Dependency security updates** — Resolved 12 of 19 Dependabot alerts across root and UI packages: upgraded `vite` (5→8), `postcss`, `tough-cookie`, `xml2js`, `uuid` (UI), `brace-expansion`, `picomatch`, `cookie`, `tmp`, and `@azure/identity` (UI). Remaining 7 alerts are blocked by `azurite → @azure/ms-rest-js` (deprecated Azure SDK) and require an upstream azurite fix.

---

## [v1.4.1] — Initial public release

### Added
- **Core framework** — `hasteutils` Python library with data models, processors, runners, and workflow definitions
- **API backend** — Three Azure Function Apps: main REST API (`hastefuncapi`), queue processor (`hastefuncqueues`), and TiTiler tile server (`titilerfuncapi`)
- **React frontend** — Single-page application deployed to Azure Static Web Apps with Azure Maps integration and MSAL authentication
- **Azure Batch integration** — Distributed training and imagery-prep jobs running on configurable GPU/CPU pools
- **Docker images** — `hastetraining` and `hasteimageryprep` images published to Azure Container Registry
- **Infrastructure scripts** — Terraform-based setup (`setup/setup_infra.sh`) and shell-based application deployment (`setup/deploy_apps.sh`)
- **GitHub Actions workflows** — Docker build-and-push and full Azure deployment pipelines
- **Jupyter Book documentation** — Architecture overview, API reference, deployment guide, and development guide
- **Local development support** — `docker-compose` stack, Azurite storage emulator, conda environment, and VSCode launch/task configuration

---
