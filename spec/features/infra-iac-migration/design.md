# Technical Design: Infrastructure as Code Migration (Bicep + azd)

## Overview

Replace the imperative bash setup with declarative Bicep modules under `infra/`,
orchestrated by the Azure Developer CLI (`azd`) via a root `azure.yaml`.
`azd provision` applies the Bicep (subscription-scoped `main.bicep`);
`azd deploy` publishes the three Function Apps and the Static Web App; PowerShell
hooks cover the imperative tail. This mirrors the topology in
[`docs/architecture.md`](../../../docs/architecture.md) without changing the
runtime.

## Architecture

### Provisioning Flow

```
azd up
  ├─ provision  ──▶ az deployment sub create  (infra/main.bicep)
  │                   ├─ resource group
  │                   └─ modules/*.bicep  (identity, storage, network,
  │                        monitoring, apim, functions, batch, frontend,
  │                        frontdoor*)            * feature-flagged, default off
  │
  ├─ (postprovision hook, pwsh)
  │     └─ import APIM operations from live Function metadata
  │
  ├─ deploy  ──▶ Function Apps (api/hastefuncapi, hastefuncqueues,
  │                titilerfuncapi)  +  Static Web App (ui/)
  │
  └─ (postdeploy hook, pwsh)
        ├─ upload config_admin_settings.json to blob
        └─ create bootstrap user invitation
```

### Directory Layout

```
azure.yaml                     # azd: services + hooks
infra/
  main.bicep                   # targetScope = 'subscription'; creates RG, calls modules
  main.bicepparam              # typed params (prefix, location, suffix, flags, shared refs)
  abbreviations.json           # optional: standard resource-type abbreviations
  modules/
    identity.bicep             # user-assigned identity + built-in role assignments
    roles.bicep                # custom role definition(s) + assignments (e.g. SWA invitation role)
    storage.bicep              # functions storage + premium file share + network rules
    network.bicep              # vnet, subnets (default/func/batch), nsg, service endpoints
    monitoring.bicep           # Log Analytics workspace + App Insights components
    communication.bicep        # ACS + Email Service + sender domain (managed or custom)
    apim.bicep                 # APIM service + APIs + backends + operations + policies
    functions.bicep            # 3 Flex Consumption Function Apps (params per app)
    batch.bicep                # batch account (create) OR existing ref + pool (autoscale, container, vnet)
    frontend.bicep             # Static Web App + Azure Maps
    frontdoor.bicep            # Front Door profile + WAF policy (deployed only if enabled)
  deploy/
    postprovision.ps1          # APIM operation import
    postdeploy.ps1             # admin-settings upload + user invitation
```

### Module Responsibilities

| Module | Replaces (in `setup_infra.sh`) | Key resources |
|---|---|---|
| `identity.bicep` | `create_group_and_umi`, ACR/storage role assignments | `Microsoft.ManagedIdentity/userAssignedIdentities`, `roleAssignments` |
| `roles.bicep` | (manual, as-built) custom role + assignment letting the API function app issue SWA invitations, plus the Azure Maps Data Reader grant | `Microsoft.Authorization/roleDefinitions` (custom role granting `microsoft.web/staticSites/*`) + `roleAssignments` to the API app's **system-assigned** identity scoped to the SWA, and an `Azure Maps Data Reader` assignment to the same identity scoped to the Maps account |
| `storage.bicep` | `create_storage`, network rules | `Microsoft.Storage/storageAccounts` (Standard_LRS + Premium FileStorage), file share |
| `network.bicep` | `configure_networking_and_logging` | `virtualNetworks`, subnets, `networkSecurityGroups` |
| `monitoring.bicep` | Log Analytics + per-app App Insights | `Microsoft.OperationalInsights/workspaces`, `Microsoft.Insights/components` |
| `communication.bicep` | (new) provisions the email backend so its connection string is a deploy output, not a manual secret | `Microsoft.Communication/communicationServices`, `emailServices`, `emailServices/domains` |
| `apim.bicep` | `create_apim`, `add_function_to_apim_with_arm`, `deploy_*_operations` | `Microsoft.ApiManagement/service` + `apis`/`backends`/`operations`/`policies` |
| `functions.bicep` | `create_function_app` (×3) | `Microsoft.Web/sites` (FlexConsumption), VNet integration, storage mount |
| `batch.bicep` | `create_batch_pool` (+ the never-implemented `create_batch_acct`) | `Microsoft.Batch/batchAccounts` (create mode) and/or `batchAccounts/pools`; dual create-vs-BYO (see below) |
| `frontend.bicep` | `create_static_app`, `create_map_account` | `Microsoft.Web/staticSites`, `Microsoft.Maps/accounts` |
| `frontdoor.bicep` | `create_frontdoor_and_waf` | `Microsoft.Cdn/profiles`, `frontDoorWebApplicationFirewallPolicies` |

### As-built inventory & the `what-if` scope limitation

Some resources in the live environment were created **manually**, outside the
bash scripts, and must be modeled in Bicep up front. They will **not** be
surfaced by `what-if`: subscription-scoped deployments run in **incremental**
mode, so `what-if` only reports changes to resources that are *already declared
in the template*. An undeclared, manually-created resource appears as neither an
add, a delete, nor a warning — it is invisible. `what-if` is therefore a drift
detector for declared resources, **not** a discovery tool for undeclared ones.

Consequently, the first Phase 1 task is an explicit **as-built inventory** of the
live environment (resources in the RG(s) **plus** subscription-scope custom role
definitions and assignments) which becomes the source of truth for what Bicep
must reproduce. Known manual resources captured so far:

| Manual resource | Why it exists | Modeled by |
|---|---|---|
| Azure Communication Services (Email) | Email backend created out-of-band; connection string was pasted manually. The operated deployment uses a **custom** sender domain (`notifications.<your-domain>`) | `communication.bicep` |
| Custom role for SWA user management (`microsoft.web/staticSites/*`) + assignment | The API function app calls `createUserInvitation` on the SWA at runtime ([user.py](../../../hastelib/src/hastegeo/core/utils/user.py)). The role is assigned at the **SWA scope** to the app's **system-assigned** identity (not the UMI) | `roles.bicep` |
| `Azure Maps Data Reader` on the Maps account → API app **system-assigned** identity | The API app reads Azure Maps tiles/data at runtime via `DefaultAzureCredential` (the system-assigned identity). A missing grant caused a production outage (2026-06-25); now modeled so every environment receives it automatically | `roles.bicep` (built-in role `423170ca-a8f6-4b0f-8487-9e4eb8f49bfa`) |
| Narrower legacy invitation role (`Microsoft.Web/staticSites/createinvitation/action`) | **Unassigned** — superseded by the broader SWA user-management role. **Decision (2026-06-25): retire — not modeled in IaC.** | n/a (retire) |
| Shared Batch account | The GPU pool lives on a shared Batch account in a separate resource group, not the env RG | `batch.bicep` in `Existing` mode |
| Shared container registry (ACR) | The training/imageryprep images are pulled from a shared ACR that lives in `sharedResourceGroup`, not the env RG | `identity.bicep` references it by `sharedAcrName`; the env UMI's `AcrPull` assignment is **cross-RG** (scoped to `sharedResourceGroup`) |

Capture the custom roles with
`az role definition list --custom-role-only true` and their assignments with
`az role assignment list --assignee <principal-id>` before authoring
`roles.bicep`. Note the API function app carries **both** system-assigned and
user-assigned identities; `DefaultAzureCredential` uses the **system-assigned**
one for the invitation call, so `functions.bicep` must enable both.

## Parameter Model

`main.bicepparam` replaces the positional CLI args and `<REPLACE_ME>` edits.

| Param | Type | Default | Replaces |
|---|---|---|---|
| `resourcePrefix` | string | — | `$3` |
| `location` | string | — | `$4` |
| `randomSuffix` | string | — | `$5` |
| `sharedResourceGroup` | string | '' (→ env RG) | `SHARED_RESOURCE_GROUP` — RG holding BYO shared resources (Batch, ACR) |
| `batchAccountMode` | `'Create'` \| `'Existing'` | `Create` | (new) create a Batch account in the env RG, or reference a shared one |
| `existingBatchAccountName` | string | '' | `SHARED_BATCH_ACCOUNT` — required when mode is `Existing`; looked up in `sharedResourceGroup` |
| `batchPoolMode` | `'Create'` \| `'Existing'` | `Create` | (new) create the GPU pool, or reference an existing one |
| `existingBatchPoolId` | string | '' | `SHARED_BATCH_POOL_ID` — required when pool mode is `Existing` |
| `batchPoolVmSize` | string | `STANDARD_NC40ads_H100_v5` | inline pool `vmSize` |
| `batchPoolMaxNodes` | int | `3` | inline `cappedPoolSize` |
| `batchPoolSubnetName` | string | `batch-subnet` | `SHARED_BATCH_POOL_SUBNET` |
| `sharedAcrName` | string | '' | `SHARED_ACR_NAME` |
| `trainingImage` | string | `hastetraining:1.4.1` | `SHARED_TRAINING_IMAGE` |
| `imageryprepImage` | string | `hasteimageryprep:1.4.1` | `SHARED_IMAGERYPREP_IMAGE` |
| `staticAppDomain` | string | — | `STATIC_APP_DOMAIN` |
| `apimPublisherEmail` | string | — | `SHARED_APIM_PUBLISHER_EMAIL` |
| `apimPublisherName` | string | `AI For Good Lab` | `SHARED_APIM_PUBLISHER_NAME` |
| `emailSenderDomainType` | `'AzureManaged'` \| `'Custom'` | `AzureManaged` | (new) sender-domain mode |
| `emailCustomDomain` | string | '' | (new) custom sender domain, e.g. `notifications.<domain>`; required when type is `Custom` |
| `enableFrontDoor` | bool | `false` | `EnableFrontDoor` |
| `deployFunctionApp` | bool | `true` | `DeployFunctionApp` |
| `deployStaticWebApp` | bool | `true` | `DeployStaticWebApp` |

### Secrets & email backend

**There are no human-supplied secrets.** The email backend (Azure Communication
Services) is provisioned by `communication.bicep`, so the email connection
string is a deploy-time `listKeys()` output, not a manually pasted value. The
other sensitive values (storage/batch keys, Function master key) are likewise
deploy-time outputs wired into app settings by Bicep — a human never sees them.

The sender domain is parameterized for open-source flexibility:

| `emailSenderDomainType` | Behavior | DNS step |
|---|---|---|
| `AzureManaged` (default) | Provisions an Azure-managed `*.azurecomm.net` sender domain | None — fully automated `azd up` |
| `Custom` | Provisions a custom sender domain (`emailCustomDomain`, e.g. `notifications.<domain>`) | One-time manual TXT/SPF/DKIM verification; a hook prints the records to add |

The operated deployment sets `Custom`; partners/forks can stay on the
zero-DNS `AzureManaged` default. Moving ACS + Batch to managed-identity auth
(eliminating even the derived connection strings) is tracked as a follow-up;
this migration does **not** introduce a Key Vault.

### Batch: create vs. bring-your-own

GPU compute runs on an Azure Batch pool. The original bash script only ever
supported **bring-your-own** — `create_batch_acct` errored out and required a
pre-existing `SHARED_BATCH_ACCOUNT`. The operated environment reflects this: its
pool lives on a shared Batch account in a separate resource group, not in the
env RG. The Bicep design supports **both** modes via two independent
toggles, so a self-contained fork can create everything while an operated
deployment keeps reusing shared GPU capacity.

| `batchAccountMode` | Behavior |
|---|---|
| `Create` (default) | `batch.bicep` provisions a new `Microsoft.Batch/batchAccounts` in the **env RG**. Fully self-contained — good for OSS forks. |
| `Existing` | References an existing account `existingBatchAccountName` in `sharedResourceGroup` via an `existing` resource. No account is created. This is the operated-deployment path. |

| `batchPoolMode` | Behavior |
|---|---|
| `Create` (default) | Creates the GPU pool (`Microsoft.Batch/batchAccounts/pools`) on the resolved account. When the account is `Existing` **in a different RG**, the pool sub-module is deployed with `scope: resourceGroup(sharedResourceGroup)` — i.e. it **creates the pool inside the shared account's RG**. Pool name derives from `resourcePrefix`/`randomSuffix` (matching the bash `BATCH_POOL_ID`). |
| `Existing` | References a pre-existing pool `existingBatchPoolId` for app-settings wiring only; **no writes at all**. Use when the shared pool is managed elsewhere. |

The pool always carries the env UMI (`UserAssigned`) for ACR pull, uses
`batchPoolSubnetName` in the env VNet, and is parameterized on `batchPoolVmSize`
/ `batchPoolMaxNodes` (replacing the hard-coded inline values). Function apps
receive the batch account endpoint, pool id, and — for parity — the account key
via `listKeys()` on the resolved account (MI-based Batch auth is the same
follow-up noted above).

> **The shared ACR is also cross-RG.** When `sharedAcrName` resolves to a
> registry in `sharedResourceGroup` (the operated-deployment case), the env
> UMI's `AcrPull` role assignment must be scoped to that registry in the shared
> RG — it is a cross-RG `roleAssignment` authored as a sub-module deployed with
> `scope: resourceGroup(sharedResourceGroup)`. Same blast-radius rules as the
> Batch pool write below: `what-if` covers both RGs, the assignment is additive
> (a new `AcrPull` grant for the env UMI, never touching the registry or other
> assignments), and the deploying identity needs role-assignment write on the
> shared RG. In `Create`-everything forks where the ACR lives in the env RG, the
> assignment stays in-RG and no shared-RG permission is needed.

> **Cross-RG pool creation is supported.** `batchAccountMode=Existing` +
> `batchPoolMode=Create` is allowed: the pool sub-module targets
> `scope: resourceGroup(sharedResourceGroup)` and creates *only the pool* on the
> shared account — it never touches the shared account itself or any sibling
> resource. This keeps day-to-day operation painless (forks and an operated
> deployment can both spin up pools on the shared GPU account) at the cost of a
> write into a shared RG.

> **Subscription Batch-account quota is 1.** Verified 2026-06-25: the
> subscription caps Batch accounts at 1, already consumed by the operated
> environment's shared account (`existingBatchAccountName`, which lives in
> `sharedResourceGroup`). A second environment in the same subscription
> therefore **cannot** use `batchAccountMode=Create` — preflight fails with
> `SubscriptionAccountQuotaExceeded`. Multi-environment operated deployments
> must use `batchAccountMode=Existing` + `batchPoolMode=Create`, which adds only
> a new pool on the shared account. `Create` mode remains valid for forks that
> deploy into their own subscription.
>
> **Blast-radius caution:** because this path writes into a resource group you
> may share with other workloads, `what-if` must be reviewed against **both**
> the env RG and `sharedResourceGroup`, and the deploying identity needs
> `Microsoft.Batch/batchAccounts/pools/write` on the shared account. Pool
> creation is additive (a new named pool); it must not redefine or delete
> existing pools on the shared account.

## azd Service Definitions (`azure.yaml`)

| Service | host | language | project | Maps to |
|---|---|---|---|---|
| `api` | function | python | `api/hastefuncapi` | `FUNCTION_API` |
| `titiler` | function | python | `api/titilerfuncapi` | `FUNCTION_TITILER_API` |
| `queues` | function | python | `api/hastefuncqueues` | `FUNCTION_QUEUE_API` |
| `web` | staticwebapp | js | `ui` | `STATIC_WEB_APP` |

`azd deploy` builds each (`func ... publish` equivalent, `swa build` for `web`)
and pushes using the resource names emitted as Bicep outputs.

## Imperative Tail (PowerShell Hooks)

Some steps are inherently imperative — they read live runtime state or call
control-plane REST APIs that have no clean declarative form:

| Hook | Step | Why not Bicep |
|---|---|---|
| `postprovision.ps1` | Import APIM operations from `az functionapp function list` | Operations are discovered from deployed function metadata at runtime |
| `postprovision.ps1` | Print custom email-domain DNS records (only when `emailSenderDomainType` is `Custom`) | DNS verification for a custom sender domain is an out-of-band, one-time action |
| `postdeploy.ps1` | Upload `config_admin_settings.json` to the `data` container | Data-plane blob write, gated by temporary network-rule toggle |
| `postdeploy.ps1` | Create bootstrap user invitation via `createUserInvitation` REST | One-shot control-plane action, returns a short-lived URL |

These are written in `pwsh` (cross-platform) and replace the equivalent bash
functions. They are idempotent (check-before-create) like the originals.

## Behavior & Logic

### Core Flow

1. Engineer sets `azd env` values (prefix, location, suffix, shared refs).
2. `azd provision` runs `infra/main.bicep` at subscription scope, creating the
   RG and all modules. `--preview` surfaces `what-if` first.
3. `postprovision.ps1` registers APIM operations.
4. `azd deploy` publishes the three Function Apps and the Static Web App.
5. `postdeploy.ps1` uploads admin settings and issues the bootstrap invitation.

### Edge Cases

| Case | Expected Behavior |
|---|---|
| Re-run against existing environment | `what-if` shows no changes; modules are idempotent by resource id |
| Shared Batch/ACR already provided | Modules reference existing resources by name; skip creation |
| Front Door disabled | `frontdoor.bicep` module is not deployed (`if (enableFrontDoor)`) |
| APIM operation already exists | Hook checks before create (parity with current bash) |
| Storage network rules block admin upload | Hook temporarily allows, uploads, re-denies (parity with current bash) |

### Error Handling

| Error Condition | Response | Recovery |
|---|---|---|
| Bicep validation failure | `azd provision` aborts before any change | Fix module, re-run |
| `what-if` shows unexpected deletes | Operator reviews and cancels | Reconcile Bicep with live state |
| Function publish failure | `azd deploy` reports per-service | Re-run `azd deploy <service>` |
| Hook failure | Non-zero exit surfaces in azd output | Re-run hook (idempotent) |

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| azd environment values | string | — | `azd env set` / `.azure/<env>/.env` | prefix, location, suffix, shared refs |
| `enableFrontDoor` | bool | false | `main.bicepparam` | Toggles Front Door + WAF module |
| Function app settings | various | — | `functions.bicep` | env, queue names, storage URLs, batch refs |
| Secrets / derived keys | output | — | Bicep `listKeys()` → app settings | ACS email conn string, storage/batch keys — never human-supplied |

## Observability

- **Provision logs:** `azd provision` output + `az deployment sub` operation log.
- **Drift detection:** `azd provision --preview` (`what-if`) on a schedule or
  pre-deploy.
- **App telemetry:** unchanged — App Insights components provisioned by
  `monitoring.bicep`, wired to the Function Apps.

## Open Questions

- [x] **CI integration — resolved (2026-06-25): follow-up.** The deploy CI is
      [.github/workflows/deploy-apps.yml](../../../.github/workflows/deploy-apps.yml)
      → `.github/scripts/deploy_apps.sh` (not `azure-pipelines.yml`, which only
      runs security/compliance scans). The switch to `azd provision`/`azd deploy`
      stays a stretch phase (Phase 5), done as its own PR after local `what-if`
      parity is proven. Rationale: avoid migrating IaC and CI auth (OIDC) at once.
- [x] **Key Vault — resolved (2026-06-25): no Key Vault.** ACS is provisioned
      in-IaC (`communication.bicep`), so the email connection string becomes a
      deploy-time output and the last human-supplied secret disappears. Remaining
      derived values are wired by Bicep into app settings. Managed-identity auth
      for ACS + Batch is a follow-up. Sender domain is parameterized
      (`AzureManaged` default, `Custom` opt-in) for OSS flexibility.
- [x] **Resource naming — resolved (2026-06-25): keep `prefix` + `randomSuffix`.**
      Not azd's `resourceToken`. Existing deployments are named with the
      prefix/suffix scheme; matching them keeps `what-if` clean (a different
      token would propose destroy/recreate of every resource). `randomSuffix`
      may default to a generated value for brand-new environments but stays
      explicit/overridable so existing envs map exactly.
