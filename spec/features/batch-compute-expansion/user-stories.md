# User Stories: Batch compute expansion + multi-tenant shared GPU pools

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| ML Engineer | Runs training / inference / embedding jobs from the HASTE app | Jobs land on GPU compute quickly; no per-env pool wrangling |
| Platform Operator | Deploys and operates HASTE environments + shared compute | Serve many envs within scarce GPU quota; add an env cheaply |
| External Partner | Runs a demo environment with their own data | Their imagery/results are never visible to another tenant |

> Disaster Analyst / Project Manager personas are unaffected by this (compute-layer) feature.

---

## Stories

### US-001: Provision shared GPU pools once for many environments

**As a** Platform Operator,
**I want to** provision a small set of shared GPU pools that many environments submit to,
**So that** scarce GPU quota is pooled centrally instead of fragmented across per-env pools.

**Priority:** P1
**Estimate:** M
**Component(s):** `infra/shared-pools.bicep`, `infra/modules/batchPool.bicep`

**Acceptance Criteria:**

```gherkin
Given the shared Batch account and an ACR-pull-only identity exist
When I deploy shared-pools.bicep with sharedGroup=dev
Then two pools <prefix>-shared-dev-{h100,t4}-pool are created, autoscale enabled,
  low-priority, at 0 nodes (scale-to-zero), consuming no GPU while idle
```

```gherkin
Given the shared pools already exist
When I redeploy shared-pools.bicep with the same parameters
Then the deployment is idempotent (no destructive change to the pools)
```

**Notes:** Pool count stays at a handful regardless of tenant count (account pool-quota is ~20).

---

### US-002: Add a new environment with zero shared-compute changes

**As a** Platform Operator,
**I want to** onboard a new demo environment onto the shared pools without modifying them,
**So that** onboarding scales to 20+ tenants without touching a shared, semi-immutable resource.

**Priority:** P1
**Estimate:** S
**Component(s):** env `.env` / Function App settings, `infra/modules/functionApp.bicep`

**Acceptance Criteria:**

```gherkin
Given the shared pools exist
When I deploy a new env that points AZURE_BATCH_*_POOL_IDS at the shared pool ids,
  sets AZURE_BATCH_USE_SAS=true, and whose Function App identity holds Storage Blob Delegator
Then the env can submit jobs to the shared pools with no change to the pools or their identity
```

**Notes:** No per-tenant UMI is attached to the pool; the pool is never mutated per tenant.

---

### US-003: A tenant cannot access another tenant's data

**As an** External Partner,
**I want** my environment's Batch tasks to read/write only my own storage,
**So that** running on shared compute never exposes my imagery/results to another tenant.

**Priority:** P0
**Estimate:** M
**Component(s):** `hastelib/runners/azure_batch.py`, `functionApp.bicep`

**Acceptance Criteria:**

```gherkin
Given two tenants submit jobs to the same shared pool
When tenant A's task uses tenant A's per-job SAS to access tenant B's container
Then the access is denied by Azure (BlobAccessDenied) — isolation is enforced at
  the credential boundary, not by application correctness
```

**Notes:** PoC-validated 2026-07-14 (see design.md, "Data isolation → Validation"). The pool holds no standing storage access.

---

### US-004: Training routes to H100, spilling over to T4

**As an** ML Engineer,
**I want** training jobs to prefer H100 nodes and spill over to T4 when H100 is busy,
**So that** my job starts on the best available GPU instead of queuing behind a saturated tier.

**Priority:** P1
**Estimate:** M
**Component(s):** `hastelib/config.py`, `hastelib/runners/azure_batch.py`, `processors/train.py`

**Acceptance Criteria:**

```gherkin
Given AZURE_BATCH_TRAINING_POOL_IDS="h100-pool,t4-pool"
When a training task is submitted and the H100 pool has an idle node
Then the task is bound to the H100 pool at submit time
```

```gherkin
Given the H100 pool has no idle node but the T4 pool does
When a training task is submitted
Then the task spills over to the T4 pool
```

```gherkin
Given neither candidate pool has an idle node
When a training task is submitted
Then it is bound to the preferred (first) pool, which scales up / queues
```

**Notes:** Inference/embedding use `AZURE_BATCH_INFERENCE_POOL_IDS` (T4-first); imageryprep/artifacts use `AZURE_BATCH_IMAGERYPREP_POOL_IDS`.

---

### US-005: Demo burst preserves scarce dedicated GPU quota

**As a** Platform Operator,
**I want** demo bursts to run on low-priority/spot nodes that scale to zero when idle,
**So that** scarce *dedicated* GPU quota stays reserved for dev/prod and idle demos cost nothing.

**Priority:** P2
**Estimate:** S
**Component(s):** `infra/shared-pools.bicep`, `infra/modules/batchPool.bicep`

**Acceptance Criteria:**

```gherkin
Given a shared demo pool with no queued tasks
When it is idle
Then it holds 0 nodes (scale-to-zero) and consumes no GPU/cost
```

```gherkin
Given demo pools are low-priority
When they scale up
Then they draw from the low-priority quota bucket, not the dedicated GPU quota
```

**Notes:** Requires demo workloads to tolerate preemption (Batch reschedules preempted low-priority tasks).

---

### US-006: No single tenant starves the shared pool

**As a** Platform Operator,
**I want** per-tenant limits so one environment can't monopolize the shared pool,
**So that** 20+ demo tenants get fair access to shared compute.

**Priority:** P2
**Estimate:** M
**Component(s):** `hastelib` (submit path), Batch job priority

**Acceptance Criteria:**

```gherkin
Given a tenant already has its cap of active tasks on the shared pool
When it submits another task
Then the task is held/queued rather than admitted ahead of other tenants
```

**Notes:** Phase 1 = per-tenant concurrent-task caps + Batch job priority. Escalate to an admission broker only if starvation is observed.

---

## Agent Assignment Map

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend + infra (hastelib runners/config, Bicep) | Yes |
| `backend-validation` | Validates backend/infra against specs, conventions, tests | No (validates only) |
| `security` | Reviews the multi-tenant isolation model + new grants/deps | No (reports only) |
| `orchestrator` | Tracks spec status | No (observes only) |

> UI / GIS agents are not involved (no UI or imagery-provider change).

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `backend-dev` | `backend-validation` | IaC (shared-pools/batchPool) |
| US-002 | `backend-dev` | `backend-validation` | env wiring + Blob Delegator grant |
| US-003 | `backend-dev` | `security`, `backend-validation` | isolation boundary — security-reviewed |
| US-004 | `backend-dev` | `backend-validation` | `select_pool` routing |
| US-005 | `backend-dev` | `backend-validation` | autoscale/spot config |
| US-006 | `backend-dev` | `backend-validation` | fairness caps |

### Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-003 | Isolation | `backend-dev` | `hastelib` + `functionApp.bicep` |
| P1 | US-001 | Pools (IaC) | `backend-dev` | `infra/` |
| P1 | US-002 | Onboarding | `backend-dev` | env `.env` |
| P1 | US-004 | Routing | `backend-dev` | `hastelib` |
| P2 | US-005 | Cost/quota | `backend-dev` | `infra/` |
| P2 | US-006 | Fairness | `backend-dev` | `hastelib` |

## Out of Scope

- [ ] Migrating dev/prod off their existing single dedicated pool onto H100+T4 pairs — future work.
- [ ] An admission-broker fair-share service — only if per-tenant caps prove insufficient.
- [ ] Migrating to the `azure-batch` 15.x (track-2) SDK — tracked separately.
- [ ] Cross-region GPU bursting.
