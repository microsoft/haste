# Rollout Plan: Batch compute expansion + multi-tenant shared GPU pools

## Rollout Strategy

**Type:** feature-flag + phased
**Target date:** TBD (gated on low-priority GPU quota)

Every runtime behavior change is behind per-environment app settings that default
to the **legacy** single-pool, pool-identity path. Shipping the code is therefore a
no-op until an environment opts in — so code rollout and behavior rollout are
decoupled.

## Deployment Targets

| Component | Deployment Method | Target |
|---|---|---|
| Shared pools (`shared-pools.bicep`) | `az deployment group create` (standalone) | Shared Batch account RG |
| `haste-shared-acr-umi` + AcrPull | `az` / Bicep | Shared framework RG |
| `hastelib` (v2.1.0) | Docker rebuild + func app deploy (`azd deploy`) | `api` / `queues` Function Apps |
| `Storage Blob Delegator` grant | `functionApp.bicep` via `azd up`/`provision` | Per env storage |
| Per-env opt-in settings | `azd env set` → app settings | `api` / `queues` app settings |

## Feature Flags

| Flag | Location | Default | Description | Kill Switch? |
|---|---|---|---|---|
| `AZURE_BATCH_USE_SAS` | `api`/`queues` app setting | `false` | Per-job SAS blob I/O vs. pool identity | yes (set `false`) |
| `AZURE_BATCH_MANAGE_POOLS` | app setting | `true` | Runner auto-creates/resizes its pool | yes (set `true`) |
| `AZURE_BATCH_TRAINING_POOL_IDS` / `_INFERENCE_POOL_IDS` / `_IMAGERYPREP_POOL_IDS` | app setting | single pool id | Ordered candidate pools | yes (unset → single pool) |

Reverting all three restores exact prior behavior with no redeploy of code.

## Rollout Phases

### Phase 0: Prerequisites

- [ ] Low-priority GPU quota increase granted (H100=40c, T4=16c per node).
- [x] Shared pools deployed (`<prefix>-shared-dev-*`, 0 nodes) + `haste-shared-acr-umi`.
- [x] v2.1.0 code merged with flags defaulting to legacy.
- [ ] Confirm demo workloads are preemption-safe (spot).

### Phase 1: Ship code (no behavior change)

- **Target:** all envs (via normal deploy).
- **Deployment:** merge v2.1.0; `azd up`/`deploy` applies the `Storage Blob Delegator` grant. Flags stay at defaults.
- **Success criteria:**
  - [ ] Existing envs behave identically (single pool, pool identity) — no regression.
  - [ ] `Storage Blob Delegator` present on each env's Function App identity.
- **Rollback trigger:** any regression on an existing env → revert branch.

### Phase 2: Enable on dev1 + dev2 (internal)

- **Target:** dev1 + dev2 pointed at `<prefix>-shared-dev-*`.
- **Deployment:** set `USE_SAS=true`, `MANAGE_POOLS=false`, `*_POOL_IDS`=shared on both.
- **Success criteria (E2E, see test-plan.md):**
  - [ ] Training + inference from both envs run on the shared pools.
  - [ ] Cross-env access denied (dev1's SAS cannot read dev2's storage).
  - [ ] Routing + spillover behave as designed; pools scale to zero when idle.
- **Rollback trigger:** isolation failure, SAS/auth errors, or job failures → unset the flags (immediate).

### Phase 3: Onboard demo envs

- **Target:** demo environments → `<prefix>-shared-demo-*` (deploy `shared-pools.bicep` with `HASTE_SHARED_GROUP=demo`).
- **Per env:** own storage + `Storage Blob Delegator` + point `*_POOL_IDS` at the shared demo pools.
- **Success criteria:**
  - [ ] Each demo runs jobs on shared compute with isolated data.
  - [ ] Adding an env requires **no** shared-pool change.
- **Feature flag cleanup:** none — the flags are the long-term opt-in until every env migrates (then the SAS path can become default).

### (Optional) Destructive cleanup of legacy per-env pools

Only after all traffic is on shared pools, and with explicit confirmation:
create-new → repoint → **drain** jobs bound to old pool ids → delete old pools.

## Rollback Plan

| Step | Action | Owner | ETA |
|---|---|---|---|
| 1 | Unset `USE_SAS` / `MANAGE_POOLS` / `*_POOL_IDS` on the affected env | Platform Operator | immediate |
| 2 | (If code-level) revert the v2.1.0 branch / redeploy previous | backend-dev | < 15 min |
| 3 | Verify jobs submit to the env's original pool with pool identity | Platform Operator | |

**Cosmos data rollback required?** no — no schema/data change.
**Blob artifacts cleanup needed?** no — same containers/paths; only the transfer credential changed.

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Baseline | Alert Threshold |
|---|---|---|---|
| Batch task failure rate | Azure Batch metrics | pre-rollout rate | sustained increase |
| `BlobAccessDenied` on task I/O | Batch task failure info | 0 (expected only for the isolation *test*) | any in normal runs |
| Pool node allocation failures | Batch metrics | 0 | any (quota/capacity signal) |
| Shared pool node-hours | Batch metrics | 0 idle | budget ceiling |
| SAS mint errors (`getUserDelegationKey`) | Function App logs / App Insights | 0 | any |

### Alerts to Configure

| Alert | Condition | Severity | Notify |
|---|---|---|---|
| Task auth failures | `BlobAccessDenied` / SAS mint errors in normal runs | P1 | eng team |
| Allocation failures | pool can't scale up (quota) | P2 | Platform Operator |

## Communication Plan

| Audience | Channel | When | Message |
|---|---|---|---|
| Engineering team | GitHub PR / Teams | Pre-deploy | Rollout plan + flag semantics |
| Demo owners / partners | — | Before onboarding | Their env moves to shared compute; data stays isolated |

## Post-Rollout Checklist

- [ ] Flags documented in `docs/configuration.md` (done)
- [ ] `CHANGELOG.md` updated (done — `[Unreleased]`)
- [ ] GitHub Pages docs rebuilt (`docs-deploy.yml`)
- [ ] Legacy per-env pools cleaned up (only after full migration + confirm)
- [ ] Update `design.md` Build status + this spec's `README.md` status → `implemented`
