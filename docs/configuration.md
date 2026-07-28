# Configuration Guide

HASTE environments are configured with the Azure Developer CLI. Every setting is
supplied with `azd env set <NAME> <value>` **before** `azd up`; the values are
read by [`infra/main.bicepparam`](https://github.com/microsoft/haste/blob/main/infra/main.bicepparam) at provision time and
by the deploy hooks in [`deploy/`](https://github.com/microsoft/haste/tree/main/deploy). Defaults live in
`main.bicepparam`, so an unset variable falls back to a sensible value.

This guide documents each configuration mode. For the end-to-end workflow, see
[`setup/README.md`](https://github.com/microsoft/haste/blob/main/setup/README.md) and [`deployment.md`](deployment.md).

## Contents

- [Core settings](#core-settings)
- [Batch (create vs. bring-your-own)](#batch-create-vs-bring-your-own)
- [Batch image tags and pool immutability](#batch-image-tags-and-pool-immutability)
- [Shared multi-tenant GPU pools](#shared-multi-tenant-gpu-pools)
- [Email sender domain](#email-sender-domain)
- [Front Door](#front-door)
- [Development mode](#development-mode)
- [First-admin bootstrap](#first-admin-bootstrap)
- [Cleaning up an environment](#cleaning-up-an-environment)

## Core settings

| Variable | Default | Purpose |
|---|---|---|
| `HASTE_RESOURCE_PREFIX` | `haste` | Prefix for all resource names. Generic default; override per deployment. |
| `HASTE_RANDOM_SUFFIX` | `dev1` | Per-environment suffix; keeps names unique. |
| `AZURE_LOCATION` | `westus2` | Azure region. |
| `HASTE_APIM_PUBLISHER_EMAIL` | — | APIM publisher email (required). |
| `HASTE_APIM_PUBLISHER_NAME` | `AI For Good Lab` | APIM publisher name. |
| `HASTE_SHARED_RESOURCE_GROUP` | env RG | Resource group holding bring-your-own shared resources (Batch, ACR). |
| `HASTE_SHARED_ACR_NAME` | — | Shared Azure Container Registry name (without `.azurecr.io`). |

Resource names are `HASTE_RESOURCE_PREFIX` + `HASTE_RANDOM_SUFFIX` based (not
azd's `resourceToken`) so `what-if` stays clean against existing deployments.

## Batch (create vs. bring-your-own)

HASTE runs GPU workloads on Azure Batch. Both the Batch **account** and the GPU
**pool** can either be created in the environment resource group or reused from a
shared resource group.

| Variable | Default | Values | Purpose |
|---|---|---|---|
| `HASTE_BATCH_ACCOUNT_MODE` | `Create` | `Create` \| `Existing` | Create a Batch account in the env RG, or reference a shared one. |
| `HASTE_EXISTING_BATCH_ACCOUNT` | — | account name | Required when the account mode is `Existing`; looked up in `HASTE_SHARED_RESOURCE_GROUP`. |
| `HASTE_BATCH_POOL_MODE` | `Create` | `Create` \| `Existing` | Create the GPU pool, or reference an existing one. |
| `HASTE_EXISTING_BATCH_POOL_ID` | — | pool resource id | Required when the pool mode is `Existing`. |

Additional pool parameters (`batchPoolVmSize`, `batchPoolMaxNodes`,
`batchPoolSubnetName`) have defaults in [`infra/main.bicep`](https://github.com/microsoft/haste/blob/main/infra/main.bicep)
and can be overridden by adding them to `main.bicepparam`.

Common combinations:

- **Self-contained fork** — `HASTE_BATCH_ACCOUNT_MODE=Create` and
  `HASTE_BATCH_POOL_MODE=Create` create a Batch account and a GPU pool in the
  environment resource group.
- **Shared account, own pool** — `HASTE_BATCH_ACCOUNT_MODE=Existing` with
  `HASTE_BATCH_POOL_MODE=Create` creates only a new named pool on the shared
  account, in the shared resource group, via a cross-RG-scoped sub-module. It
  never modifies the account or sibling pools.
- **Shared account and pool** — both set to `Existing` reference the account and
  pool for app-settings wiring only; nothing is written to the shared resource
  group.

When the pool is created on a shared account, review `what-if` against **both**
the environment resource group and `HASTE_SHARED_RESOURCE_GROUP`, and make sure
the deploy identity has pool-write on the shared account.

## Batch image tags and pool immutability

The training and imageryprep container images feed **two** places: the Batch pool
(as pre-fetched `containerImageNames`) and the `api`/`queues` app settings (which
tell the runner what tag to launch tasks with).

| Variable | Default | Purpose |
|---|---|---|
| `HASTE_TRAINING_IMAGE` | `hastetraining:1.4.1` | Training image `repo:tag`. |
| `HASTE_IMAGERYPREP_IMAGE` | `hasteimageryprep:1.4.1` | Imageryprep image `repo:tag`. |

A Batch pool's `deploymentConfiguration` is **immutable** — you cannot change a
pool's image tags after creation. Two consequences:

- **Bumping a tag** requires recreating the pool (delete and re-provision), not
  an in-place update.
- **Reusing a shared pool** (`HASTE_BATCH_POOL_MODE=Existing`) means the app
  settings must use a tag the pool and the shared ACR actually have. This is a
  mostly harmless constraint, because each task submits its own image tag at
  runtime and Batch pulls it if the node doesn't already have it — but the app
  settings still need a valid tag.

To make this transparent, the `preprovision` hook
[`deploy/resolve-batch-image-tags.ps1`](https://github.com/microsoft/haste/blob/main/deploy/resolve-batch-image-tags.ps1)
reads the existing pool's `containerImageNames` and sets `HASTE_TRAINING_IMAGE` /
`HASTE_IMAGERYPREP_IMAGE` for you when `HASTE_BATCH_POOL_MODE=Existing`. It runs
only in that mode and never clobbers a tag you set explicitly — set either
variable yourself to override the auto-resolved value.

## Shared multi-tenant GPU pools

For deployments that run many environments against **scarce GPU quota**, HASTE
supports a small set of **shared, multi-tenant** Batch pools (H100 for training,
T4 for inference/imageryprep + spillover) instead of one pool per environment, so
GPU quota is pooled and rationed centrally rather than fragmented. See
[`spec/features/batch-compute-expansion/`](https://github.com/microsoft/haste/tree/main/spec/features/batch-compute-expansion)
for the full design.

**Creating the pools.** The shared pools are provisioned by
[`infra/shared-pools.bicep`](https://github.com/microsoft/haste/blob/main/infra/shared-pools.bicep)
— a standalone deployment into the shared Batch account's resource group,
separate from `azd up` — configured by
[`infra/shared-pools.bicepparam`](https://github.com/microsoft/haste/blob/main/infra/shared-pools.bicepparam):

```bash
az deployment group create -g <shared-rg> \
  --parameters infra/shared-pools.bicepparam
```

Pools are named `<prefix>-shared-<group>-<tier>-pool` (e.g. the dev-group H100
pool); `HASTE_SHARED_GROUP` selects the group (`dev`, `demo`, …). They autoscale
on **dedicated or low-priority** nodes (configurable via `HASTE_SHARED_NODE_TYPE`)
within a central per-pool core-quota ceiling. A scarce tier (H100) can keep a warm
floor instead of scaling to zero — under regional GPU
evaluation** until capacity frees, whereas a one-shot fixed resize gets stuck in
its error state. The pool identity is used **only** for ACR pull
(`haste-shared-acr-umi`) — it holds no storage access.

Shared-pool deploy knobs (env vars read by `shared-pools.bicep`):

| Variable | Default | Purpose |
|---|---|---|
| `HASTE_SHARED_GROUP` | `dev` | Pool group (`dev`, `demo`, …) — drives the pool names. |
| `HASTE_SHARED_NODE_TYPE` | `LowPriority` | Node cost tier: `LowPriority` (spot) or `Dedicated`. |
| `HASTE_SHARED_H100_SCALE_MODE` | `Autoscale` | `Autoscale`, or `Fixed` reserved baseline for the scarce H100 tier. |
| `HASTE_SHARED_H100_MIN_NODES` | `0` | H100 autoscale floor (>0 keeps chasing/holding a warm node). |
| `HASTE_SHARED_T4_MIN_NODES` / `HASTE_SHARED_T4_MAX_NODES` | `0` / `2` | T4 autoscale floor / cap. |
| `HASTE_SHARED_BATCH_SUBNET_ID` | — | Shared hub batch-subnet to VNet-inject both pools into (see Blob↔Batch networking below). |

**Data isolation.** Tenants share compute but not data: each job mints a
time-limited **user-delegation SAS** scoped to its own storage container, so a
tenant's task can never read another tenant's data. This requires the submitting
Function App identity to hold **Storage Blob Delegator** on its storage account
(granted in `functionApp.bicep`).

**Blob↔Batch networking.** SAS is an *auth* boundary, not network reach — each
tenant storage is `Deny`, so the pools must additionally be *network-allowed* to
it or blob I/O fails with `403 AuthorizationFailure`. The shared pools are
VNet-injected into a **shared hub batch-subnet** (`haste-hub-vnet/batch-subnet`,
carrying the `Microsoft.Storage` service endpoint), and **each tenant's storage
allowlists that subnet** with a VNet rule. Onboarding a new env is *just that one
storage rule* — wired in `storage.bicep` via `HASTE_SHARED_BATCH_SUBNET_ID` so it
lands on `azd provision`; the shared pools are never touched. Two one-time
prerequisites per hub (not per env): create the subnet, and grant the *Microsoft
Azure Batch* service principal `Network Contributor` on it so Batch can
VNet-inject. `HASTE_SHARED_BATCH_SUBNET_ID` is read by **both** the shared-pools
deploy (which subnet to inject the pools into) and each env deploy (which subnet
its storage allowlists). Full design:
[`networking.md`](https://github.com/microsoft/haste/blob/main/spec/features/batch-compute-expansion/networking.md).

**Per-environment app settings** (set on the `api`/`queues` Function Apps to opt
an environment into the shared pools — all default to the legacy single-pool,
pool-identity behavior, so existing environments are unaffected until opted in):

| Variable | Default | Purpose |
|---|---|---|
| `AZURE_BATCH_TRAINING_POOL_IDS` | `AZURE_BATCH_TRAINING_POOL_ID` | Ordered candidate pools for training (preference-first, spillover-second), comma-separated. |
| `AZURE_BATCH_INFERENCE_POOL_IDS` | training pool | Ordered candidate pools for inference/embedding (e.g. T4-first). |
| `AZURE_BATCH_IMAGERYPREP_POOL_IDS` | `AZURE_BATCH_IMAGERYPREP_POOL_ID` | Ordered candidate pools for imageryprep/artifacts. |
| `AZURE_BATCH_USE_SAS` | `false` | Use per-job user-delegation SAS for blob I/O instead of the pool's managed identity. Required for shared pools. |
| `AZURE_BATCH_MANAGE_POOLS` | `true` | Whether the runner auto-creates/resizes its pool. Set `false` for pre-created autoscale pools (resize fails on an autoscale pool). |

The runner picks a pool from the candidate list **at submit time** — the first
with an idle node, otherwise the preferred (first) pool, which scales up / queues.

These are emitted by both deploy paths: set them as GitHub Environment
**secrets** (`BATCH_TRAINING_POOL_IDS`, `BATCH_INFERENCE_POOL_IDS`,
`BATCH_IMAGERYPREP_POOL_IDS`, `BATCH_USE_SAS`, `BATCH_MANAGE_POOLS`,
`BATCH_TRAINING_POOL_ID`, `BATCH_IMAGERYPREP_POOL_ID`) for
[`deploy-apps.yml`](../.github/workflows/deploy-apps.yml), or as the
corresponding `infra/main.bicepparam` values for the Bicep path.

> **Secrets, not variables.** Resource naming is treated as sensitive in this
> repo (as `RESOURCE_PREFIX`, `LOCATION` and friends already are). GitHub masks
> secret values in Actions logs but does **not** mask variables, and this repo's
> workflow logs are public.

> **`*_POOL_ID` (singular) also names the Batch job.** `TRAINING_BATCH_JOB_ID`
> and friends default to the matching pool id, so the value must be **identical
> on the api and queues apps** — the queues app submits under that job id and
> the api app reads status back from it. Pointing it at a pool that no longer
> exists leaves a job permanently bound to a deleted pool; the runner now
> rebinds such a job to the pool it selected, but the setting should still be
> corrected.

### Keeping settings in sync

`AZURE_BATCH_REGISTRY_SERVER` was previously emitted as
`AZURE_BATCH_REGISTRY_SERVER_URL`. The legacy name is still read as a fallback
(and any `https://` prefix is stripped), so environments provisioned before the
rename keep working — but operators should rename the application setting.

Any variable the code requires must be emitted by **both**
[`deploy_apps.sh`](../.github/scripts/deploy_apps.sh) and
[`functions.bicep`](../infra/modules/functions.bicep).
[`check_env_drift.py`](../.github/scripts/check_env_drift.py) enforces this on
every PR via the `Config drift` workflow.

## Email sender domain

The email backend (Azure Communication Services) is provisioned in-IaC, so its
connection string is a deploy-time output rather than a manually pasted secret.

| Variable | Default | Values | Purpose |
|---|---|---|---|
| `HASTE_EMAIL_SENDER_DOMAIN_TYPE` | `AzureManaged` | `AzureManaged` \| `Custom` | Sender-domain strategy. |
| `HASTE_EMAIL_CUSTOM_DOMAIN` | — | domain | Required when the type is `Custom` (e.g. `notifications.example.com`). |

- **AzureManaged** provisions an `azurecomm.net` sender domain with no DNS step —
  the default, best for forks and quick environments.
- **Custom** provisions a custom sender domain. DNS verification (TXT/SPF/DKIM
  records) lives in the customer's DNS zone and is an out-of-band, one-time step.

No Key Vault is introduced; the connection string is wired from a `listKeys()`
output to the Function App settings.

## Front Door

Azure Front Door and its WAF are a feature-flagged module, deployed only when
enabled.

| Variable | Default | Purpose |
|---|---|---|
| `HASTE_ENABLE_FRONT_DOOR` | `false` | Provision Front Door + WAF in front of the app. |

## Development mode

Development mode is a **dev-only** switch. It must never be `true` in production.

| Variable | Default | Purpose |
|---|---|---|
| `HASTE_DEVELOPMENT_MODE` | `false` | Anonymous Function auth + auto-provisioning of users as administrators. |

When `true`, the API uses anonymous auth and `GetUserById` auto-creates any
unknown caller as an administrator — convenient for local and throwaway
environments, unacceptable for production. When `false` (the default and the
production setting), Functions are key-protected (the postdeploy hook injects the
host key into the APIM backends) and unknown users are rejected until an admin
adds them.

The Docker Compose UI image pre-fills `administrators` in the SWA emulator's
mock-login form. The source `staticwebapp.config.json` used for production is
unchanged.

## First-admin bootstrap

Production uses `DEVELOPMENT_MODE=false`, so users are managed explicitly and are
**not** auto-provisioned as administrators. That creates a bootstrap problem: an
admin is needed to add the first users, but a fresh environment has none. The
postdeploy hooks solve it by seeding a first admin.

| Variable | Default | Purpose |
|---|---|---|
| `HASTE_FIRST_ADMIN_EMAIL` | signed-in user | Email of the first administrator. |

- **Interactive deploys** — if `HASTE_FIRST_ADMIN_EMAIL` is unset, the seed uses
  the signed-in deployer's email
  ([`deploy/seed-storage-defaults.ps1`](https://github.com/microsoft/haste/blob/main/deploy/seed-storage-defaults.ps1)),
  writes it into `users_acl.json` as an administrator, and invites it to the
  Static Web App ([`deploy/invite-user.ps1`](https://github.com/microsoft/haste/blob/main/deploy/invite-user.ps1)).
- **Non-interactive / CI / service-principal deploys** — there is no signed-in
  user, so **set `HASTE_FIRST_ADMIN_EMAIL`**. Without it, the first-admin seed is
  skipped and the environment has no administrator.

Both hooks are idempotent (skip-if-exists / dedup). After the first admin signs
in, subsequent users are added through the app's admin user-management flow — the
first-admin seed is a one-time bootstrap, not the ongoing mechanism.

## Cleaning up an environment

Deleting an environment does not immediately free its name. APIM, Front Door, and
Batch resources are **soft-deleted** and retained by Azure for a day or two, so
you cannot reuse the same `HASTE_RESOURCE_PREFIX` + `HASTE_RANDOM_SUFFIX`
combination right away.

To tear down and reuse a name sooner:

```bash
# Delete the environment's resources.
azd down --force --purge

# APIM must be purged from its soft-deleted state before the name is free.
az apim deletedservice list -o table
az apim deletedservice purge --service-name <name-from-the-list> --location <region>
```

`azd down --purge` purges soft-deletable resources it manages; a shared Batch
**pool** created on a shared account is additive, so remove it explicitly if it
is no longer needed. Otherwise, choose a new suffix and let Azure auto-purge the
old resources.
