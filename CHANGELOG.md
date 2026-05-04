# Changelog

All notable changes to HASTE are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows the Docker image tags defined in the CI workflows (see [.github/workflows/](.github/workflows/)).

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
