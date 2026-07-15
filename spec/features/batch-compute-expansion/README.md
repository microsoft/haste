# Feature: Batch compute expansion + multi-tenant shared GPU pools

**Status:** in-progress
**Author:** HASTE engineering team
**Date:** 2026-07-14
**Target Release:** TBD
**Priority:** P1
**Work Item:** TBD

## Summary

Expand HASTE Batch compute to two GPU tiers (H100 for training, T4 for
inference/imageryprep/overflow) with capacity-aware routing, and re-architect
demo compute so that **many demo environments (targeting 20+) share a small set
of GPU pools** while keeping each environment's data/metadata fully isolated.
The scarce resource — GPU quota — is pooled and rationed centrally instead of
fragmented across per-env pools.

## Motivation

- **GPU quota is scarce and hard to obtain.** Per-env pools strand quota: an idle
  node in env A cannot serve env B. A shared pool keeps every scarce node busy
  whenever *any* tenant has work.
- **Per-env pools do not scale.** The Batch account allows ~20 pools total; 20
  demo envs × 2 tiers = 40 pools — physically impossible. Sharing keeps the pool
  count at a handful regardless of tenant count.
- **Uncoordinated autoscale blows quota.** 20 independently-autoscaling pools
  would exceed the account core quota and cause allocation failures. One shared,
  centrally-capped burst pool rations the scarce nodes.
- **Single fixed pool per workload today.** `config.py` exposes one
  `training_pool_id` and one `imageprep_pool_id`; the runner binds one pool at
  init (`azure_batch.py`). No tiering, no routing, no overflow.

## Non-negotiable constraint: data isolation on shared compute

Tasks from different tenants may run on the same shared node. Isolation must be
enforced at the **credential boundary**, not by application correctness. The
pool holds **no standing data access**; each job receives a short-TTL
**user-delegation SAS** scoped to exactly its own container, minted by the
submitting Function App (which already knows the tenant). Adding tenant #21
requires **zero pool/compute changes** — only its storage + a SAS-minting grant.

Rejected alternative: a shared pool identity with blob grants on every tenant's
storage — that is shared compute *and* shared data access, defeating isolation.
Also rejected: attaching every tenant's UMI to the pool — bounded by identity
limits and requires mutating a shared, semi-immutable pool per tenant.

## Success Criteria

- [ ] Two GPU tiers per compute group: H100 (`Standard_NC40ads_H100_v5`) and
      T4 (`Standard_NC16as_T4_v3`), created and managed in IaC (not the SDK
      `create_pool_if_not_exists` path).
- [ ] Capacity-aware routing: training → H100 first, spill to T4; inference /
      imageryprep → T4 first, spill to H100; "free" = idle dedicated (or
      under-max autoscale) node.
- [ ] N demo envs (validated at ≥ 4, designed for 20+) submit to **shared**
      demo pools; each env's Batch tasks can read/write **only** its own storage,
      proven by a cross-tenant access-denied test.
- [ ] Shared-demo pools autoscale within a **single central core-quota ceiling**;
      dev/prod get reserved (fixed) capacity.
- [ ] Adding a new demo env requires no pool or shared-compute change.
- [ ] Per-tenant fairness: no single demo can starve the others.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib` `config.py` | Pool ids → ordered candidate lists per workload |
| `hastelib` `azure_batch.py` | `select_pool` routing; bind pool at submit; SAS URLs replace `identity_reference`; drop SDK pool creation for shared pools |
| `hastelib` processors (train, inference, embedding, imagery, artifacts) | Pass candidate lists + workload preference; mint per-job SAS |
| `hastelib` data layer / artifact storage | User-delegation SAS minting helper |
| `infra/modules/batchPool.bicep` | Parameterize SKU, scale-mode (fixed vs autoscale), node type (dedicated vs low-priority), optional VNet, ACR-pull-only identity |
| `infra/shared-pools.bicep` + `.bicepparam` | Shared multi-tenant pool set (create-once per group, referenced by envs) |
| `infra/modules/functionApp.bicep` | `Storage Blob Delegator` grant so the app can mint user-delegation SAS |
| `infra/main.bicepparam` + env `.env` | Generic `haste` prefix default; candidate pool-id + SAS/manage-pool env vars |

## Related Specs

| Spec | Relationship |
|---|---|
| [infra-iac-migration](../infra-iac-migration/README.md) | Owns the Bicep/azd that now creates the pools; this feature extends `batchPool.bicep`. Pool creation moved out of the SDK per that migration. |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [plan.md](plan.md) | Execution plan: phases, milestones, agent summary | approved |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius, security | approved |
| [user-stories.md](user-stories.md) | User stories & acceptance criteria | approved |
| [design.md](design.md) | Technical design: topology, isolation, routing, fairness, IaC + app | approved |
| [test-plan.md](test-plan.md) | Test strategy & coverage matrix | approved |
| [rollout.md](rollout.md) | Rollout phases, opt-in flags, rollback, monitoring | approved |
| data-model.md | Cosmos/Blob/Data Lake schema changes | n/a — no schema changes |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-14 | Shared multi-tenant pools (not per-env) for dev + demo groups; prod stays dedicated | Scarce GPU quota + ~20-pool account limit; per-env pools fragment quota and don't scale to 20+ tenants. |
| 2026-07-14 | Data isolation via per-job **user-delegation SAS**, not a shared pool identity | Enforces isolation at the credential boundary, not app correctness; adding a tenant needs zero pool changes. POC-validated. |
| 2026-07-14 | **Uniform** per-job SAS on every pool (one code path) | Simpler than SAS-for-shared + identity-for-dedicated; single maintained path. |
| 2026-07-14 | Demo burst on **low-priority / spot** nodes | Separate quota bucket; preserves scarce *dedicated* GPU for dev/prod. |
| 2026-07-14 | Fairness = per-tenant task caps + Batch job priority (Phase 1) | Ship simple; add an admission broker only if starvation is observed. |
| 2026-07-14 | Shared pools deploy into the existing shared framework RG | Where the Batch account + ACR already live; clean logical ownership, no new RG. |
| 2026-07-14 | Generic-default IaC (prefix defaults to `haste`, BYO account/ACR) | Reusable by other partners; this deployment overrides via `shared-pools.bicepparam`. |
| 2026-07-14 | Pin `azure-batch==14.2.0` | 15.x track-2 rewrite restructures the model API the code uses; migration tracked separately. |

## Remaining gates (before/during build)

- Confirm preemption-safety of demo workloads (spot).
- Request low-priority GPU quota for demo burst.
- ✅ ~~embedding models `/mnt` mount~~ — resolved: no submit path uses the mount.
- **Destructive confirm:** delete the 6 existing pools after draining jobs bound
  to old pool ids (create-new → repoint → drain → delete-old).
