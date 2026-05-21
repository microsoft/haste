# Changelog

All notable changes to HASTE are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows the Docker image tags defined in the CI workflows (see [.github/workflows/](.github/workflows/)).

---

## [v1.4.5] — Per-environment deploy configuration

### Changed
- **`deploy-apps.yml` now drives per-target config from GitHub Environments** instead of workflow_dispatch inputs. The dispatch form collapses to 5 fields (environment, component, training/imageprep/app tags); all environment-specific values live as environment-scoped secrets. **Operators forking this repo must create a GitHub Environment per deployment target and populate the secrets documented in [`.github/workflows/README.md`](.github/workflows/README.md) before running the workflow.** ([#28](https://github.com/microsoft/haste/pull/28))
- **`ENVIRONMENT_TYPE` is now a per-environment secret** rather than implicitly the GitHub Environment name, decoupling the application's runtime environment type (`dev`/`staging`/`prod`) from operator-chosen environment labels. ([#28](https://github.com/microsoft/haste/pull/28))
- **Selective component deploy** — the dispatch form has a `component` dropdown (`funcapi` / `funcqueue` / `titiler` / `swa` / `all`) so operators can redeploy a single component without rebuilding and redeploying the rest. ([#28](https://github.com/microsoft/haste/pull/28))

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
