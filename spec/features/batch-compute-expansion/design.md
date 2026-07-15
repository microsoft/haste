# Design: Batch compute expansion + multi-tenant shared GPU pools

## Overview

HASTE runs GPU workloads (training, inference, embedding, imageryprep) on Azure
Batch. This design replaces the single fixed pool per workload with two GPU tiers
(H100 for training; T4 for inference/imageryprep + spillover) and a small set of
**shared, multi-tenant** pools, so many environments share scarce GPU quota
instead of fragmenting it across per-env pools. Data isolation on shared compute
is enforced by a **per-job user-delegation SAS** (the pool holds no standing
storage access); jobs are routed to a pool from an ordered candidate list at
submit time. See [user-stories.md](user-stories.md) for goals,
[impact-analysis.md](impact-analysis.md) for risk, [test-plan.md](test-plan.md)
for verification, and [rollout.md](rollout.md) for the phased rollout.

## Architecture

### Pool topology

One shared Batch account in a shared resource group (westus2). Example account
quota: ~446 shared dedicated cores, pool quota 20, low-priority 6 (request an
increase for demo burst — see [rollout.md](rollout.md)).

Pool names follow the generic `${prefix}-shared-${group}-${tier}-pool` (prefix
defaults to `haste`; a partner overrides it — shown as `<prefix>` below).

| Group | H100 pool (`NC40ads_H100_v5`, 40c) | T4 pool (`NC16as_T4_v3`, 16c) | Scale | Node type | Tenancy | Envs |
|---|---|---|---|---|---|---|
| shared-dev | `<prefix>-shared-dev-h100-pool` | `<prefix>-shared-dev-t4-pool` | autoscale, min 0 | low-priority / spot | **multi** | dev1, dev2 |
| shared-demo | `<prefix>-shared-demo-h100-pool` | `<prefix>-shared-demo-t4-pool` | autoscale, min 0 | low-priority / spot | **multi** | demo1–N |
| prod | `<prefix>-haste-prod-pool` (existing) | *(optional, TBD)* | fixed | dedicated | single | prod |

**shared-dev** and **shared-demo** pools are multi-tenant (data isolation = per-job
SAS, below); the same `shared-pools.bicep` template produces each group via
`sharedGroup`. **prod** stays single-tenant on its dedicated pool (guaranteed
capacity + isolation-by-dedication). Autoscale ceilings (`maxNodes` per pool) are
set so combined low-priority usage stays within the (to-be-increased) low-priority
GPU quota.

## Data isolation (the core design)

**Decision: uniform per-job SAS on *every* pool** — one code path, not two. Data
access is never standing on any pool; each pool keeps only an ACR-pull identity.
The multi-tenant shared-dev / shared-demo pools rely on SAS as their sole data
boundary; prod additionally has isolation-by-dedication.

### How task storage auth works today

`azure_batch.py` never puts storage credentials inside the container. Input
(`ResourceFile`), output (`OutputFileBlobContainerDestination`), and the optional
models mount all carry
`identity_reference=ComputeNodeIdentityReference(resource_id=<pool UMI>)`.
Batch performs the transfer under that identity. **A referenced identity must be
attached to the pool** — so this model is inherently one-tenant.

### Target: per-job user-delegation SAS

The submitting Function App knows the tenant. For **every** job (all pools) it
mints a **user-delegation SAS** (signed by the env identity via
`get_user_delegation_key`, no account key) scoped to that tenant's container and
prefix, with a short TTL, read for inputs / write for outputs. It embeds the SAS
in the blob URL and passes it to Batch:

- `ResourceFile(storage_container_url="https://<sa>.blob.core.windows.net/<c>?<sas>", …)` — **no** `identity_reference`.
- `OutputFileBlobContainerDestination(container_url="https://<sa>…<c>?<sas>", …)` — **no** `identity_reference`.

Each pool then needs **only** an ACR-pull identity (dev/prod: their env UMI;
shared-demo: `haste-shared-acr-umi` with `AcrPull` on the shared ACR). No pool
holds storage grants. A compromised node holds, at most, the SAS of its
currently-running tasks, scoped to one tenant's container. Every submitting
Function App identity needs `Storage Blob Delegator` on its own storage account to
mint the SAS (granted in `functionApp.bicep`).

### Why this scales

Adding tenant #21 = create its storage + grant `Storage Blob Delegator` + point
its pool-id env vars at the shared pools. **No pool mutation, no new identity on
the pool, no redeploy of the shared compute.**

### Models mount caveat

Blob **mounts are pool-level**, fixed at pool creation — they cannot be per-tenant
on a shared pool. **Verified non-issue:** no submit path uses the mount —
`add_task` calls `create_pool_if_not_exists` without `storage_account_name`, and
`embedding.py` (the model-heavy flow) uses the standard `ResourceFile`/`OutputFile`
path. The mount code is dead for current flows. A future flow needing models on
shared pools would deliver them per-task via SAS `ResourceFile`s.

### Validation (PoC, 2026-07-14) — PASSED

Proven on a throwaway low-priority CPU pool in the shared account with a real
**user-delegation SAS** (minted via `Storage Blob Delegator`, `skoid`/`sktid`
present — no account key):

- **SAS Batch I/O works.** A task with a container-scoped SAS on `ResourceFile`
  (download) *and* `OutputFileBlobContainerDestination` (upload) — no
  `identity_reference`, no UMI on the pool — completed exitCode 0 and wrote its
  output blob. The mechanism swap is a drop-in.
- **Tenant isolation holds.** A task using tenant-A's container-scoped SAS to read
  tenant-B's blob failed with `BlobAccessDenied` (UserError). The credential
  boundary is enforced by Azure, not app code.
- **ACR-pull-only shared identity works.** `haste-shared-acr-umi` (AcrPull on the
  shared ACR) **authenticated and downloaded** the real `hastetraining:2.0.0` on a
  pool referencing only that UMI. The cheap CPU test VM hit `DiskFull` only because
  Batch stores images on the node temp disk (16 GB on D2s_v3), which the GPU pools'
  large NVMe disks dwarf — auth path proven; disk is a test-VM artifact.

This retired the core architectural risks (SAS I/O, isolation, shared-identity ACR
pull).

## Behavior & Logic

### Capacity-aware routing

- Config exposes ordered candidate lists instead of single ids:
  `AZURE_BATCH_TRAINING_POOL_IDS="h100,t4"`, `AZURE_BATCH_INFERENCE_POOL_IDS="t4,h100"`.
- `select_pool(candidates)` in `azure_batch.py`: return the first candidate with an
  **idle node** (spillover to a free tier); if none is idle, return the preferred
  (first) candidate and let it scale up / queue. A single candidate is returned
  with no API calls.
- Pool binding moves **out of `AzureBatchRunner.__init__`** to submit time, so
  `add_task` targets the pool chosen per task. `manage_pools=false` skips
  SDK create/resize + the node-wait for pre-created autoscale pools (both fail /
  deadlock on a scale-to-zero pool).

### Fairness (shared pools, 20+ tenants)

Isolation is solved above; fairness is the remaining hard problem. **Decision:
start simple, escalate only if needed.**

- **Phase 1 (ship):** per-tenant concurrent-task cap enforced app-side + Batch
  **job priority** (interactive/inference > long training). No new service.
- **Phase 2 (only if starvation is observed):** a lightweight admission broker that
  admits queued jobs round-robin / weighted across tenants.

## Configuration

### IaC (`infra/`)

- **`modules/batchPool.bicep`** — parameterized `scaleMode` (`Fixed` | `Autoscale`),
  `nodeType` (`Dedicated` | `LowPriority`), `fixedNodeCount`, `minNodes` (autoscale
  floor; 0 = scale-to-zero), optional VNet injection. One pool per invocation.
  Backward-compatible defaults.
- **`shared-pools.bicep`** (+ `shared-pools.bicepparam`) — instantiates the H100+T4
  pair for a group, deployed **standalone** into the shared account's RG (separate
  from `azd up`). `sharedGroup` selects `dev` / `demo` / …. Uses the ACR-pull-only
  `haste-shared-acr-umi`.
- **`modules/functionApp.bicep`** — grants the app identity `Storage Blob Delegator`
  (mint SAS).
- **`main.bicepparam`** — `HASTE_RESOURCE_PREFIX` defaults to the generic `haste`;
  partners override the prefix + BYO account/ACR via `shared-pools.bicepparam`.

### Environment settings (per-env opt-in)

Set on the `api`/`queues` Function Apps; all default to the legacy single-pool,
pool-identity path (see [docs/configuration.md](../../../docs/configuration.md#shared-multi-tenant-gpu-pools)):

| Variable | Default | Purpose |
|---|---|---|
| `AZURE_BATCH_{TRAINING,INFERENCE,IMAGERYPREP}_POOL_IDS` | single pool id | Ordered candidate pools (comma-separated) |
| `AZURE_BATCH_USE_SAS` | `false` | Per-job SAS blob I/O vs. pool identity |
| `AZURE_BATCH_MANAGE_POOLS` | `true` | Runner auto-creates/resizes its pool (`false` for pre-created autoscale pools) |

## Migration & rollout

Full phased plan in [rollout.md](rollout.md). Summary (non-destructive order):
request quota → create shared pools alongside existing → ship v2.1.0 (flags off) →
enable on dev1+dev2 and validate E2E → onboard demos → (optional, confirmed)
drain + delete legacy per-env pools.

## Observability

Signals to watch during/after rollout (alerts detailed in
[rollout.md](rollout.md#monitoring--alerting)):

- **Batch task failure rate** and any `BlobAccessDenied` in normal runs (SAS
  scope/grant problems — expected only in the isolation *test*).
- **Node allocation failures** on the shared pools (low-priority GPU quota signal).
- **`getUserDelegationKey` errors** in Function App logs (missing `Storage Blob
  Delegator`).
- **Shared pool node-hours** vs. the low-priority budget ceiling.

## Build status (2026-07-14)

- ✅ `batchPool.bicep` parameterized; `shared-pools.bicep` deployed →
  `<prefix>-shared-dev-{h100,t4}-pool` **live**, autoscale low-priority, 0 nodes
  (scale-to-zero), ACR-pull via `haste-shared-acr-umi`. Waiting on the quota bump
  to scale up.
- ✅ **v2.1.0 app code (hastelib)** — candidate-list routing + `select_pool`,
  per-job SAS, `manage_pools` gate, all 5 processors, `Storage Blob Delegator` in
  `functionApp.bicep`. 9 unit tests pass. `azure-batch` pinned `==14.2.0`.
- ⬜ Finalize pool **networking** (subnet + per-tenant-storage firewall allowlisting)
  before real workloads.
- ⬜ dev/prod fixed H100+T4 pairs (they currently run their existing single pool).

## Open Questions

- **Low-priority GPU quota** increase — required before the shared pools can scale
  up (H100=40c, T4=16c per node vs. the current 6 low-priority cores).
- **Preemption-safety** of demo workloads — spot requires retry-safe / idempotent
  tasks (Batch auto-reschedules preempted low-priority tasks).
- **Shared-pool networking** — VNet subnet + per-tenant storage-firewall
  allowlisting model for VNet-injected shared pools.
- **Destructive cleanup** — deleting legacy per-env pools after draining jobs bound
  to old pool ids (create-new → repoint → drain → delete-old); needs explicit
  confirmation.
