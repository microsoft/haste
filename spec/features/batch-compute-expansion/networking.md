# Design: Blob ↔ Batch network path for shared multi-tenant pools

**Status:** approved
**Date:** 2026-07-15

## Problem

Data isolation on the shared pools is enforced by per-job user-delegation SAS
(see [design.md](design.md)). SAS is an **auth** boundary — it does not grant
**network reach**. Each tenant storage account is `defaultAction: Deny`, so a
Batch node must also be *network-allowed* to touch that account, or every blob
read/write fails with `403 AuthorizationFailure` (network denial, not a bad SAS).

The shared `*-shared-demo-*` pools were created with **no VNet injection**, so
their nodes egress from unpredictable BatchManaged public IPs that no tenant
firewall allowlists → blob↔Batch is broken for every shared-pool tenant.

## The model (proven by prod)

Prod's single-tenant pool already uses the durable pattern:

1. A subnet (`batch-subnet`) with the **`Microsoft.Storage` service endpoint**,
   no delegation.
2. The Batch pool is **VNet-injected** into it (BatchService allocation mode:
   the "Microsoft Azure Batch" SP needs subnet-join on the vnet).
3. The storage account has a **VNet rule allowlisting that subnet** — nodes reach
   blobs over the service endpoint; `Deny` still blocks everything else.

Confirmed live on `ai4glhasteprodsa`: `virtualNetworkRules` = func-subnet +
default + batch-subnet (all `Succeeded`), backing the VNet-injected prod pool.

## Multi-tenant adaptation

The shared pools live in the shared account/vnet; **each tenant's** storage
allowlists the **one shared batch subnet**. Storage VNet rules work **cross-vnet
with no peering** as long as the subnet has the `Microsoft.Storage` service
endpoint — so the pool binds to the subnet once, and tenants attach from their
own storage side.

```
                       haste-dev-vnet / batch-subnet (10.0.2.0/24, Microsoft.Storage SE)
                                          │  (pools VNet-injected here, once)
        ┌────────────────────────────────┼────────────────────────────────┐
   ai4gl-shared-demo-t4-pool                                   ai4gl-shared-demo-h100-pool
        │ node egress via service endpoint                                 │
        ▼                                                                  ▼
  demo5 storage (VNet rule: batch-subnet)   demo6 storage (VNet rule: batch-subnet)   ... demoN
```

### Why this scales (the key property)

- **Pool → subnet is set once and is immutable.** It never changes as tenants
  come and go.
- **Onboarding demoN = one VNet rule on demoN's own storage** referencing the
  shared batch-subnet. The pool is never touched. This is the storage-side
  "adding a tenant needs zero pool/compute changes" principle from
  [README.md](README.md#non-negotiable-constraint-data-isolation-on-shared-compute),
  extended to the network layer.
- The per-tenant rule is **baked into the per-env storage Bicep**, so a new
  env's normal `azd up` allowlists itself — hands-free, no shared-pool change.

The subnet immutability is a **one-time setup cost** (migrate the existing
subnet-less pools in), never a recurring per-tenant blocker.

## IaC changes

| File | Change |
|---|---|
| `infra/shared-pools.bicep` + `.bicepparam` | New `sharedBatchSubnetId` param → passed to both pools' `subnetId` (env: `HASTE_SHARED_BATCH_SUBNET_ID`). Also `h100MinNodes` (env: `HASTE_SHARED_H100_MIN_NODES`) to make the H100 autoscale floor reproducible. |
| `infra/modules/batchPool.bicep` | Already supports `subnetId` (emits `networkConfiguration` + BatchManaged public IPs when set). No change. |
| per-env storage module | Add a `virtualNetworkRules` entry for the shared batch-subnet so each tenant self-allowlists on `azd up`. |

## Concrete values (this deployment)

- Shared subnet: `haste-dev-vnet/batch-subnet` = `10.0.2.0/24`, service endpoint
  `Microsoft.Storage`, no delegation (mirrors prod's 10.0.2.0/24).
- Batch SP: `Microsoft Azure Batch` (`appId ddbf3205-c6bd-46ae-8127-60eb93363864`),
  Network Contributor on the subnet (subnet-join).
- Tenant storage rule: `ai4glhastedemo5sa` → VNet rule for the shared batch-subnet.

## One-time migration (disruptive step)

The existing `ai4gl-shared-demo-{t4,h100}-pool` were created without a subnet;
subnet is immutable, so they are **deleted and recreated** into `batch-subnet`.
Safe when no demo Batch jobs are running. For the H100 this is ~free (it holds 0
nodes under westus2 contention); the T4 briefly drops its idle baseline and
re-acquires. Recreation is via `shared-pools.bicep` with the full config
preserved (T4 autoscale min 2/max 6; H100 autoscale min 1/max 2) plus the subnet.

## Decision

Durable VNet-injection + per-tenant storage VNet rule (service-endpoint,
cross-vnet, no peering) over the band-aid (storage `Allow` / rotating-IP
allowlist). Rationale: keeps `Deny` defense-in-depth, and onboarding stays a
storage-side self-service step consistent with the shared-pool isolation model.
