# Impact Analysis: Batch compute expansion + multi-tenant shared GPU pools

## Scope of Change

### HASTE Components Affected

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core library — config | `hastelib/src/hastegeo/core/config.py` | modified (additive candidate lists + flags) | low |
| Core library — batch runner | `hastelib/src/hastegeo/core/runners/azure_batch.py` | modified (select_pool, submit-time binding, SAS, manage_pools gate) | medium |
| Core library — local runner | `hastelib/src/hastegeo/core/runners/local.py` | modified (interface parity) | low |
| Core library — processors | `hastelib/src/hastegeo/core/processors/{train,inference,embedding,imagery,artifacts}.py` | modified (pass candidate lists) | low |
| IaC — batch pool module | `infra/modules/batchPool.bicep` | modified (parameterized scale/node/VNet) | medium |
| IaC — shared pools | `infra/shared-pools.bicep` + `.bicepparam` | new | medium |
| IaC — function app roles | `infra/modules/functionApp.bicep` | modified (Storage Blob Delegator grant) | medium |
| IaC — params | `infra/main.bicepparam` | modified (generic prefix default) | low |
| Build | `hastelib/pyproject.toml` | modified (`azure-batch==14.2.0` pin) | low |

## Azure Service Impact

| Service | Change | New Cost Impact |
|---|---|---|
| Azure Batch | New shared H100+T4 pools (autoscale low-priority, scale-to-zero); `batchPool` module gains scale/node params | None while idle (0 nodes). Low-priority nodes are cheaper than dedicated; demo GPU moves to the low-priority quota bucket. |
| Blob Storage | Access pattern change: Batch task I/O uses per-job user-delegation SAS instead of the pool managed identity | None (same reads/writes; different credential) |
| Azure Functions | `api`/`queues` apps gain `Storage Blob Delegator` and mint SAS at submit time | Negligible (a cached `getUserDelegationKey` call) |
| Managed Identity | New `haste-shared-acr-umi` (ACR-pull only) for shared pools | None |

> Cosmos DB, Data Lake, Queue Storage, Static Web Apps: **no change**.

## Dependency Analysis

### Upstream Dependencies (things this feature needs)

| Dependency | Type | Status | Risk if Unavailable |
|---|---|---|---|
| Shared Batch account + ACR (shared framework RG) | infra | available | Pools can't be created |
| Low-priority GPU quota | quota | **pending increase** | Shared pools exist but can't scale up until granted |
| `Storage Blob Delegator` on the Function App identity | RBAC | new grant (in `functionApp.bicep`) | SAS minting fails → jobs can't do blob I/O in SAS mode |
| `azure-batch` 14.x model API | library | pinned `==14.2.0` | 15.x breaks the imports |

### Downstream Impact (things affected by this feature)

| Consumer | How Affected | Breaking? | Migration Needed? |
|---|---|---|---|
| Existing single-pool envs (dev1, prod, …) | New env vars all default to legacy behavior | no | no — opt-in only |
| `AzureBatchRunner` / `LocalRunner` callers | `candidate_pool_ids` added (optional) | no | no |
| Processors | Pass candidate lists (fallback to single id) | no | no |
| Batch pool definitions | Autoscale pools reject SDK resize; runner skips it when `manage_pools=false` | no (gated) | set the flag for pre-created pools |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| Cross-tenant data leakage on shared nodes | Low | Critical | Per-job container-scoped user-delegation SAS; pool holds no storage access; POC-proven `BlobAccessDenied` | backend-dev / security |
| SAS minting fails (missing `Storage Blob Delegator`) | Medium | High | Grant added in `functionApp.bicep`; verify on each env before enabling `USE_SAS` | Platform Operator |
| Autoscale pool resize/wait deadlock | Medium | High | `manage_pools=false` skips create/resize and the node-wait for pre-created pools | backend-dev |
| Spot preemption thrashes long training | Medium | Medium | Demos (short/interactive) on spot; dev/prod stay dedicated; tasks must be retry-safe | Platform Operator |
| Destructive pool rebuild orphans in-flight jobs | Low | High | Sequenced create-new → repoint → drain → delete-old (see rollout.md) | Platform Operator |
| `azure-batch` auto-upgrade breaks build | Medium | Medium | Pinned `==14.2.0` | backend-dev |
| One tenant starves the shared pool | Medium | Medium | Per-tenant task caps + job priority (Phase 1) | backend-dev |

## Performance Impact

- **Submit latency:** +1 pool-capacity check per candidate at submit time (skipped for single-candidate lists) + a cached `getUserDelegationKey` per account. Negligible.
- **Batch compute:** Higher *utilization* of scarce GPU (shared nodes never idle if any tenant has work); cold-start latency when a scale-to-zero pool spins up its first node.
- **Storage I/O:** Unchanged volume; credential path differs (SAS vs identity).
- **API / tile serving:** No change.

## Security Impact

- [x] New data classification handled? — Multi-tenant compute; isolation is the core requirement. Enforced by per-job container-scoped SAS (credential boundary), **security-reviewed** (US-003).
- [x] New secrets or connection strings required? — No standing secrets. Short-TTL user-delegation SAS minted per job (no account keys).
- [x] New RBAC? — `Storage Blob Delegator` on the Function App identity (mint SAS); ACR-pull-only UMI for shared pools (no storage access).
- [ ] New API endpoints exposed? — No.
- [ ] MSAL/Entra ID auth changes? — No.
- [ ] CORS changes? — No.
- [ ] New federated credentials? — No.

## Compliance & Data Impact

- [x] Partner data sharing agreements — Shared *compute*, isolated *data*: a tenant's task cannot read another tenant's storage. This is the explicit design guarantee.
- [ ] Geospatial data sovereignty — No region change (all westus2).
- [ ] New data retention — No.
- [x] Component Governance — One dependency change: `azure-batch` pinned (no new package). New Bicep only.

## Rollback Assessment

- **Reversibility:** fully reversible.
- **App code:** All new behavior is behind flags defaulting to legacy (`USE_SAS=false`, `MANAGE_POOLS=true`, single pool id). Reverting the flags (or the branch) restores exact prior behavior.
- **Shared pools:** Additive — deleting them affects only envs that opted in; other envs are untouched.
- **RBAC:** The `Storage Blob Delegator` grant is additive and harmless if unused.
- **Blob/Cosmos data:** No schema or data migration; nothing to roll back.
- **Estimated rollback time:** < 15 min (flip env vars / revert deploy).
