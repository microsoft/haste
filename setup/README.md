# Infrastructure setup

HASTE environments are provisioned and deployed with a single command using the
[Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/).
`azd` applies the Bicep in [`infra/`](../infra) and deploys the three Function
Apps and the Static Web App. The legacy bash scripts (`setup_infra.sh`,
`deploy_apps.sh`) have been retired — see
[ADR-0003](../spec/architecture/decisions/0003-bicep-azd-infra-migration.md) and
the [infra-iac-migration spec](../spec/features/infra-iac-migration/README.md).

## Contents

- [Prerequisites](#prerequisites)
- [Quickstart](#quickstart)
- [What `azd up` does](#what-azd-up-does)
- [Configuration](#configuration)
- [Preview changes (what-if)](#preview-changes-what-if)
- [Other files in this folder](#other-files-in-this-folder)

## Prerequisites

- An Azure subscription and rights to create resources in it.
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az`).
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) (`azd`).
- [PowerShell 7+](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) (`pwsh`) — the deploy hooks are cross-platform PowerShell.
- [Node.js](https://nodejs.org/) and the [Static Web Apps CLI](https://azure.github.io/static-web-apps-cli/) (`swa`) — used by the postdeploy hook to build and publish the UI.
- Python 3.11 (for the Function App deploys).

## Quickstart

```bash
# Authenticate (azd and az share the same login on most setups).
azd auth login
az login

# Create a new azd environment (pick a short, unique name, e.g. dev3).
azd env new dev3

# Required configuration.
azd env set HASTE_RESOURCE_PREFIX     ai4gl
azd env set HASTE_RANDOM_SUFFIX       dev3
azd env set AZURE_LOCATION            westus2
azd env set HASTE_APIM_PUBLISHER_EMAIL you@example.com

# Optional configuration — see the Configuration section below.

# Provision infrastructure and deploy the apps in one step.
azd up
```

> **Naming note:** if you delete an environment you cannot immediately reuse the
> same `HASTE_RESOURCE_PREFIX` + `HASTE_RANDOM_SUFFIX`. Some resources (APIM,
> Front Door, Batch) are soft-deleted and retained by Azure for a day or two.
> Choose a new suffix or wait for the purge (see the [housekeeping notes in the
> configuration guide](../docs/configuration.md#cleaning-up-an-environment)).

## What `azd up` does

1. **Preprovision hook** — when reusing an existing shared Batch pool, resolves
   the pool's (immutable) container image tags into `HASTE_TRAINING_IMAGE` /
   `HASTE_IMAGERYPREP_IMAGE` so the app settings match the pool automatically
   ([`deploy/resolve-batch-image-tags.ps1`](../deploy/resolve-batch-image-tags.ps1)).
2. **Provision** — applies [`infra/main.bicep`](../infra/main.bicep): resource
   group, identity and roles, network, storage, monitoring, communication
   (email), APIM, three Function Apps, Batch, the Static Web App, and the
   feature-flagged Front Door.
3. **Deploy** — publishes the `api`, `titiler`, and `queues` Function Apps.
4. **Postdeploy hook** ([`deploy/postdeploy.ps1`](../deploy/postdeploy.ps1)):
   - builds and publishes the UI to the Static Web App production environment;
   - syncs APIM operations for the deployed endpoints and injects the Function
     host key into the APIM backends;
   - seeds default admin settings and the first admin user (`users_acl.json`);
   - invites the first admin to the Static Web App and prints the invitation URL.

## Configuration

All configuration is set with `azd env set <NAME> <value>` before `azd up`. The
full matrix — Batch (create vs. bring-your-own), the email sender domain, the
Front Door flag, development mode, and the first-admin seed — is documented in
the [configuration guide](../docs/configuration.md).

Common knobs:

| Variable | Default | Purpose |
|---|---|---|
| `HASTE_RESOURCE_PREFIX` | `ai4gl` | Resource name prefix. |
| `HASTE_RANDOM_SUFFIX` | `dev1` | Per-environment suffix. |
| `AZURE_LOCATION` | `westus2` | Azure region. |
| `HASTE_APIM_PUBLISHER_EMAIL` | — | APIM publisher email. |
| `HASTE_FIRST_ADMIN_EMAIL` | signed-in user | First admin for non-interactive/CI deploys. |
| `HASTE_ENABLE_FRONT_DOOR` | `false` | Provision Front Door + WAF. |
| `HASTE_DEVELOPMENT_MODE` | `false` | Dev-only anonymous auth + auto-provisioning. Never `true` in production. |

## Preview changes (what-if)

```bash
azd provision --preview
```

This runs `az deployment sub what-if` and reports what would change against the
live environment without applying anything.

## Other files in this folder

| File | Purpose |
|---|---|
| [`config_admin_settings.json`](config_admin_settings.json) | Default admin settings (source types, base models, labeling settings) seeded to the `data` container by the postdeploy hook. |
| [`start-task.sh`](start-task.sh) | Batch node start task: formats and mounts the local NVMe disk for GPU jobs. |
| [`create_conda_env.sh`](create_conda_env.sh) | Local dev helper: builds the conda environment from `env.yml`. |
| [`install_python.ps1`](install_python.ps1) | Local dev helper: installs Python (used by the VS Code tasks). |
| [`create_invitations.sh`](create_invitations.sh) | Standalone helper for issuing Static Web App invitations outside `azd`. |
