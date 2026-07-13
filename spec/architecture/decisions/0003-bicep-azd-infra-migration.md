# ADR-0003: Migrate Infrastructure Setup to Bicep + Azure Developer CLI (azd)

**Status:** accepted
**Date:** 2026-06-25
**Deciders:** HASTE engineering team

## Context

HASTE infrastructure is currently provisioned and deployed by two large bash
scripts in `setup/`:

- `setup/setup_infra.sh` — ~1,420 lines that
  create every Azure resource (resource group, user-assigned identity,
  storage accounts, VNet/subnets/NSG, Log Analytics, APIM, three Flex
  Consumption Function Apps, Azure Batch pool, Maps, Static Web App, optional
  Front Door + WAF), then deploy the Function Apps and Static Web App,
  register APIM APIs/backends/operations/policies, set CORS, upload admin
  settings, and create the first user invitation.
- `setup/deploy_apps.sh` — ~250 lines that
  re-declare much of the same configuration to redeploy app code outside the
  pipeline.

This approach has accumulated problems:

- **Not runnable on the team's primary OS.** The scripts are bash-only and
  require `jq`; engineers work on Windows/PowerShell.
- **No preview or validation.** Resources are created with imperative
  `az ... create` calls guarded by ad-hoc `check_resource_exists` helpers.
  There is no `what-if`, no type checking, and "idempotency" is best-effort.
- **Inline ARM/Bicep as heredoc strings.** APIM imports and the Batch pool are
  embedded as escaped strings, so they cannot be linted, validated, or reused.
- **Configuration duplication and drift.** `setup_infra.sh` and
  `deploy_apps.sh` independently declare resource names, image tags, queue
  names, and app settings, and disagree on versions
  (`v1.2.0` vs `v1.4.1`).
- **Manual placeholders.** `<REPLACE_ME>` values for shared RG, Batch, ACR,
  and domain are edited in place, which is error-prone and unfriendly to
  source control.
- **Secrets in plain app settings.** `EMAIL_CONNECTION_STRING`, Batch keys,
  storage connection strings, and Function master keys are passed as
  `az functionapp config appsettings set` values rather than Key Vault
  references.

This is an architecture change to the deployment system referenced in
`spec/architecture/overview.md` and `docs/deployment.md`.

## Options Considered

### Option A: Keep bash + Azure CLI, refactor in place

- **Pros:** No new tooling; smallest immediate change.
- **Cons:** Still bash-only (won't run on Windows), no `what-if`/validation,
  inline ARM strings remain, duplication between the two scripts persists,
  already at the maintainability ceiling at ~1,670 combined lines.
- **Impact on HASTE components:** None structurally; problems persist.

### Option B: Terraform

- **Pros:** Mature, declarative, good `plan`/`apply` UX.
- **Cons:** Introduces a non-Microsoft-native IaC stack to an otherwise
  Azure/Bicep shop; discards the inline Bicep already written for APIM and the
  Batch pool; no first-class `azd` integration for the Function App + SWA
  build/publish flow; new state-management burden.
- **Impact on HASTE components:** Whole new toolchain to learn and maintain.

### Option C: Bicep modules + Azure Developer CLI (azd) — **Chosen**

- **Pros:** Microsoft-native and the lab IaC convention; declarative modules
  get `az deployment sub what-if`, type checking, and real idempotency; reuses
  the inline Bicep already present; `azd up` runs provision **and** deploy
  (Function Apps + SWA) cross-platform in one command, replacing both bash
  scripts; pre/post hooks cover the few imperative steps; feature flags become
  typed Bicep params.
- **Cons:** Engineers must install `azd`; a thin imperative tail (APIM
  operation import from live metadata, admin-settings upload, user invitation)
  still needs scripting, now in PowerShell.
- **Impact on HASTE components:** New `infra/` Bicep tree and `azure.yaml`;
  `setup/` bash scripts retired; `docs/deployment.md` and `setup/README.md`
  updated.

## Decision

Adopt **Bicep modules orchestrated by the Azure Developer CLI (`azd`)** for all
HASTE infrastructure provisioning and application deployment.

- All declarative infrastructure moves to versioned Bicep modules under
  `infra/`, with a subscription-scoped `infra/main.bicep` and a typed
  `infra/main.bicepparam`.
- An `azure.yaml` at the repo root defines the three Function App services and
  the Static Web App so `azd provision` + `azd deploy` (or `azd up`) replace
  both bash scripts.
- The imperative tail that Bicep/azd cannot express declaratively — importing
  APIM operations from live Function metadata, uploading `config_admin_settings.json`,
  and creating the bootstrap user invitation — is implemented as **PowerShell**
  `azd` post-provision / post-deploy hooks.
- The email backend (Azure Communication Services) is **provisioned in-IaC** by a
  `communication.bicep` module, so the email connection string becomes a
  deploy-time `listKeys()` output rather than a manually supplied secret. With
  that, **no human-supplied secrets remain** and **no Key Vault is introduced**;
  the remaining derived values (storage/batch keys) are wired into app settings
  by Bicep. Managed-identity auth for ACS + Batch is a follow-up. The sender
  domain is parameterized (`AzureManaged` default for zero-DNS forks, `Custom`
  opt-in for the Microsoft-operated deployment).
- Front Door + WAF is included as a **feature-flagged Bicep module**, defaulting
  to disabled, preserving the existing `EnableFrontDoor` behavior.

The migration reproduces the **current deployed state first** (validated with
`what-if` against a live resource group) before any cleanup, so the IaC is an
accurate mirror of production rather than an idealized rewrite.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Infrastructure (new) | `infra/` | New Bicep modules: identity, storage, network, monitoring, communication, apim, functions, batch, frontend, frontdoor |
| azd config (new) | `azure.yaml` | Defines Function App + SWA services and hooks |
| Deploy hooks (new) | `deploy/` | PowerShell post-provision/post-deploy scripts |
| Legacy setup | `setup/setup_infra.sh`, `setup/deploy_apps.sh` | Retired after parity confirmed |
| Setup docs | `setup/README.md` | Rewritten for azd workflow |
| Deployment docs | `docs/deployment.md` | Updated to azd workflow |

### Azure Services Affected

| Service | Change |
|---|---|
| All HASTE Azure resources | Same resources, now provisioned declaratively via Bicep instead of imperative `az` calls. No change to the runtime topology. |
| Azure Communication Services | Newly provisioned in-IaC (Email Service + sender domain) so the email connection string is a deploy-time output instead of a manually supplied secret. |

## Consequences

- **Easier:** Cross-platform deploys (Windows included); `what-if` preview
  before every change; one-command `azd up`; type-checked, source-controlled,
  reviewable infra; single source of truth for resource config; feature flags
  as typed params.
- **Harder:** Engineers must install and learn `azd`; the imperative tail still
  needs PowerShell maintenance; initial parity validation against live state
  takes care.
- **New constraints:** Infra changes go through Bicep + `what-if` review; new
  HTTP endpoints still need their APIM operation registered (now via the
  post-deploy hook rather than the bash function).
- **Impact on Docker Compose local dev stack:** None — local dev continues to
  use `docker/docker-compose.yml`; this ADR concerns cloud provisioning only.
- **Impact on CI/CD workflows:** The deploy CI
  ([.github/workflows/deploy-apps.yml](../../../.github/workflows/deploy-apps.yml) →
  `.github/scripts/deploy_apps.sh`) can switch to `azd provision`/`azd deploy`;
  tracked as a follow-up (Phase 5) in the migration plan. `azure-pipelines.yml`
  is unaffected — it only runs security/compliance scans, not deploys.
