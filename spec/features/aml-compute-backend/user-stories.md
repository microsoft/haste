# User Stories: Backend-neutral compute runner + Azure Machine Learning backend

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| ML Engineer | Runs training / inference / embedding jobs from the HASTE app | Jobs complete correctly regardless of which compute backend runs them |
| Platform Operator | Deploys and operates HASTE environments, owns GPU capacity and IaC | Add AML capacity without replacing Batch; predictable rollout/rollback |
| Disaster Analyst | Consumes finished models/inference results in the UI | Sees identical artifacts and statuses no matter which backend ran the job |
| Admin | Configures system settings, monitors compute health | Understands which backend a job used and why, for troubleshooting |

> External Partner and Project Manager personas are not directly affected by
> this compute-layer feature; see [batch-compute-expansion](../batch-compute-expansion/user-stories.md)
> for their concerns.

---

## Stories

### US-001: Runner boundary represents a HASTE execution, not a Batch task

**As an** ML Engineer,
**I want** every compute workload to be submitted through one typed,
backend-neutral contract,
**So that** adding a new compute provider never requires that provider to
emulate Azure Batch's job/task shape.

**Priority:** P0
**Estimate:** L
**Component(s):** `hastelib/src/hastegeo/core/models/compute.py`,
`hastelib/src/hastegeo/core/runners/base.py`

**Acceptance Criteria:**

```gherkin
Given the new ComputeRunner contract exists
When any processor submits a workload
Then it constructs a ComputeJobSpec and calls submit()/get_status()/
  read_output()/cancel()/finalize()/get_capacity(), never a Batch-shaped
  (job_id, task_id) method directly
```

```gherkin
Given a ComputeJobSpec with an invalid destination-relative path, a "../"
  traversal segment, an unrecognized URI scheme, or a mutable image reference
When validate() is called
Then submission is rejected before any provider API call
```

**Notes:** `rg "get_azure_batch_config|AZ_BATCH_" hastelib/src/hastegeo/core/processors`
must return no matches once complete.

---

### US-002: Submit and manage jobs on Azure Machine Learning

**As an** ML Engineer,
**I want to** run training, inference, embedding, imagery preprocessing, and
artifact packaging on Azure Machine Learning,
**So that** HASTE is not limited to Azure Batch capacity for GPU/CPU compute.

**Priority:** P0
**Estimate:** XL
**Component(s):** `hastelib/src/hastegeo/core/runners/azure_ml.py`

**Acceptance Criteria:**

```gherkin
Given a ComputeJobSpec for any of the five workloads and an AML backend
  configured for that workload
When it is submitted
Then an AML command job is created using an immutable environment version
  bound to the same container image tag/digest Batch uses, and the returned
  handle can be polled, read, cancelled, and finalized
```

```gherkin
Given an AML job is running
When HASTE polls its status
Then AML compute scaling from zero is reported as queued/preparing, not as a
  failure
```

**Notes:** Covers all five workloads — no workload is deferred.

---

### US-003: Choose a compute backend per job, including automatic routing

**As an** ML Engineer or Platform Operator,
**I want** each job to request `azure_batch`, `azure_ml`, `local`, or `auto`,
**So that** I can control placement per job while still allowing HASTE to
balance load automatically when I don't.

**Priority:** P0
**Estimate:** L
**Component(s):** `hastelib/src/hastegeo/core/runners/router.py`,
`hastelib/src/hastegeo/core/runners/execution_service.py`

**Acceptance Criteria:**

```gherkin
Given a job explicitly requests azure_ml
When it is submitted and azure_ml is configured and healthy
Then it is submitted to AML, never silently redirected to another backend
```

```gherkin
Given a job requests auto and both azure_batch and azure_ml are configured
  and healthy for its workload
When many such jobs are submitted
Then jobs are distributed across both backends using deterministic weighted
  routing, and each executionId always resolves to the same backend across
  retries
```

```gherkin
Given a job requests an explicit backend that is disabled or misconfigured
When it is submitted
Then it fails before any provider call with an actionable configuration
  error, and is never silently rerouted to a different backend
```

**Notes:** Resolution order is explicit → follow-on inheritance → workload
default → global default → `auto` policy, as detailed in
[design.md](design.md#backend-resolution-order).

---

### US-004: Compute lifecycle survives restarts and configuration changes

**As a** Platform Operator,
**I want** the backend and provider handle selected for a job to be persisted
with that job,
**So that** polling, cancellation, and finalization always address the
correct provider even after a worker restart or a default-backend change.

**Priority:** P0
**Estimate:** M
**Component(s):** `hastelib/src/hastegeo/core/models/projects.py`,
`hastelib/src/hastegeo/core/runners/execution_service.py`

**Acceptance Criteria:**

```gherkin
Given a job was submitted to azure_ml and its handle is persisted
When COMPUTE_BACKEND_DEFAULT is changed to azure_batch and the queue worker
  restarts
Then subsequent status/cancel/finalize calls for that job still address
  Azure ML, using the persisted handle
```

```gherkin
Given a legacy TrainingJob/InferenceJob/ImageryPreprocessJob/ZipJob record
  with only jobId and taskId and no computeJob handle
When it is loaded
Then HASTE synthesizes an Azure Batch ComputeJobHandle and continues polling
  it without reinterpreting it under the current default backend
```

**Notes:** No Cosmos backfill required — `computeJob` is additive.

---

### US-005: No duplicate provider job from a retried or racing submission

**As a** Platform Operator,
**I want** a submission retry or duplicate worker race to never create a
second provider compute job for the same execution,
**So that** HASTE never doubles GPU spend or produces conflicting outputs for
one logical job.

**Priority:** P0
**Estimate:** M
**Component(s):** `hastelib/src/hastegeo/core/runners/execution_service.py`

**Acceptance Criteria:**

```gherkin
Given a submission call fails with an indeterminate outcome (timeout after
  the request may have reached the provider)
When HASTE retries
Then it looks up the deterministic provider job name and reconciles against
  the existing run instead of submitting a new one
```

```gherkin
Given two queue workers race to submit the same executionId
When both call submit()
Then exactly one provider job is created; the losing worker retrieves and
  validates the existing job instead of creating a second one
```

**Notes:** Applies uniformly across Batch, AML, and local adapters.

---

### US-006: Deploy Azure Machine Learning as Disabled, Create, or Existing

**As a** Platform Operator,
**I want** AML infrastructure to support `Disabled`, `Create`, and `Existing`
modes,
**So that** I can deploy HASTE without AML, self-provision AML, or reference
an operator-provided AML workspace, without introducing standing secrets or
unwanted resource/RBAC changes.

**Priority:** P1
**Estimate:** L
**Component(s):** `infra/modules/aml{Workspace,Compute,Environment,Datastore,Role}.bicep`,
`infra/main.bicep`, `infra/main.bicepparam`

**Acceptance Criteria:**

```gherkin
Given amlMode=Disabled
When the HASTE deployment is provisioned
Then no AML resources are created; the Function App's AML_* settings
  (AML_MODE, AML_IDENTITY_MODE, and the rest) may still be present with
  inert/empty values rather than omitted from the settings collection
```

```gherkin
Given amlMode=Existing with a valid reference to an operator-provided AML
  workspace, compute, environment(s), datastore, and identity
When the HASTE deployment is provisioned
Then HASTE writes only the application settings needed to address those
  resources: it creates no AML resource and assigns no RBAC role. Granting
  the identity HASTE runs as sufficient access is the operator's
  responsibility, performed outside HASTE's IaC
```

```gherkin
Given amlMode=Create (available in source for a separately approved future
  scenario; not applied during the initial rollout)
When that scenario's deployment is provisioned
Then a workspace, scale-to-zero compute clusters, environments bound to
  HASTE's container image tags/digests, and an identity-based datastore are
  created with no account keys or passwords, and the queue Function App
  identity is granted the built-in AzureML Data Scientist role (job
  submit/read/cancel, read compute) via amlRole.bicep — ACR pull continues to
  use the existing shared acrRole grant Batch already relies on
```

**Notes:** All three modes are verified with local Bicep compilation and
static template checks. This rollout performs no Azure deployment operation
(no `az deployment ... what-if` or apply) for the AML modules; `Existing` is
the only mode applied in this rollout's Stage 1.

---

### US-007: Automatic follow-on jobs carry an explicit compute decision

**As an** ML Engineer,
**I want** automatic follow-on jobs (e.g. inference after training, artifact
packaging after inference) to have a documented, persisted backend choice,
**So that** follow-on placement is predictable rather than inferred from
whatever the process's current default happens to be.

**Priority:** P1
**Estimate:** S
**Component(s):** `hastelib/src/hastegeo/core/processors/{train,inference,artifacts}.py`

**Acceptance Criteria:**

```gherkin
Given COMPUTE_FOLLOW_ON_INHERITS_BACKEND is enabled and a training job ran on
  azure_ml
When an automatic inference follow-on is queued
Then it defaults to azure_ml if azure_ml supports inference, otherwise it
  applies the configured workload policy and records the reason
```

**Notes:** The decision is persisted with the queued request, not recomputed
from current process configuration at execution time.

---

### US-008: No standing secrets or leaked credentials in compute plumbing

**As a** Security Reviewer,
**I want** the compute-neutral runner and AML adapter to introduce no account
keys, passwords, or logged credentials,
**So that** the credential-boundary isolation principle established for
Batch is preserved as a new backend is added.

**Priority:** P0
**Estimate:** M
**Component(s):** `hastelib/src/hastegeo/core/runners/azure_ml.py`,
`hastelib/src/hastegeo/core/models/compute.py`

**Acceptance Criteria:**

```gherkin
Given AML authentication uses DefaultAzureCredential
When HASTE is deployed in any AML mode
Then no AML account key, password, or connection string appears in
  configuration, code, or logs
```

```gherkin
Given a ComputeJobHandle or log line is produced
When it is inspected
Then it contains no access token, account key, SAS token, or full signed
  input URL
```

```gherkin
Given two HASTE deployments might share one AML workspace or compute cluster
When one deployment's job attempts to access another deployment's storage
Then it is denied at the credential boundary
```

```gherkin
Given AML_IDENTITY_MODE is left at its default (user)
When an AML job is submitted
Then it runs as the submitting principal's own identity (the calling
  Function App's identity) rather than as a new standing identity, and no
  AML_MANAGED_IDENTITY_ID value is required
```

**Notes:** Requires a live negative access test, not only static review.

---

## Agent Assignment Map

Every user story must be assigned to one or more HASTE agents. The
**implementing agent** writes the code; the **validating agent** verifies
correctness against acceptance criteria. See
[Agent Architecture](../../architecture/overview.md#agent-architecture) for
full agent descriptions.

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend, API, processors, runners, data layers, IaC (Bicep) | Yes |
| `backend-validation` | Validates backend/infra code against specs, conventions, tests | No (validates only) |
| `security` | Reviews new dependencies (`azure-ai-ml`), credential handling, isolation model | No (reports only) |
| `security-validation` | Confirms `security` findings are addressed before merge | No (validates only) |
| `orchestrator` | Records what agents did, when, why; tracks spec status | No (observes only) |

> No `ui` or `gis` agent is involved — this feature has no UI change (backend
> choice is a request/configuration field, not a UI control) and no
> imagery-provider change.

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `backend-dev` | `backend-validation` | Core contract + models |
| US-002 | `backend-dev` | `backend-validation` | AML adapter; dependency `azure-ai-ml==1.34.1` reviewed and approved by `security` |
| US-003 | `backend-dev` | `backend-validation` | Router + execution service |
| US-004 | `backend-dev` | `backend-validation` | Persisted handle + legacy synthesis |
| US-005 | `backend-dev` | `backend-validation` | Idempotent submission |
| US-006 | `backend-dev` | `backend-validation`, `security` | IaC modes; Stage 1 applies `Existing` (pure reference, no RBAC); `security` reviewed keyless auth and the (unapplied) `Create`-mode RBAC design, `security-validation` confirmed |
| US-007 | `backend-dev` | `backend-validation` | Follow-on inheritance |
| US-008 | `backend-dev` | `security`, `security-validation` | Security-owned acceptance criteria; `backend-validation` confirms no functional regression |

> `orchestrator` tracks progress on all stories; not listed per row.

### Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Phase 1 — Compute models & contracts | `backend-dev` | — | `backend-validation` |
| Phase 2 — Execution service, registry, router | `backend-dev` | — | `backend-validation` |
| Phase 3 — Batch/local adapter migration | `backend-dev` | — | `backend-validation` |
| Phase 4 — Persisted handles & processor migration | `backend-dev` | — | `backend-validation` |
| Phase 5 — AML adapter & dependency | `backend-dev` | `security` | `backend-validation`, `security-validation` |
| Phase 6 — AML IaC (Disabled/Create/Existing) | `backend-dev` | `security` | `backend-validation`, `security-validation` |
| Phase 7 — Observability, rollout, docs | `backend-dev` | — | `backend-validation` |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-001 | Phase 1 | `backend-dev` | `hastelib` core models/runners |
| P0 | US-002 | Phase 5 | `backend-dev` | `hastelib` AML adapter |
| P0 | US-003 | Phase 2 | `backend-dev` | `hastelib` router/execution service |
| P0 | US-004 | Phase 4 | `backend-dev` | `hastelib` job models |
| P0 | US-005 | Phase 2 | `backend-dev` | `hastelib` execution service |
| P0 | US-008 | Phase 5, 6 | `backend-dev` | `hastelib`, `infra` |
| P1 | US-006 | Phase 6 | `backend-dev` | `infra/` |
| P1 | US-007 | Phase 4 | `backend-dev` | `hastelib` processors |

## Out of Scope

- [ ] Migrating an already-running provider job between Batch and AML mid-flight — reconciliation only, never cross-provider migration.
- [ ] Replacing Azure Batch — this feature adds AML, it does not retire Batch.
- [ ] Rewriting HASTE workloads as AML pipelines/components — command jobs already represent each workload correctly.
- [ ] Distributed multi-node training — a separate feature if a workload adopts it.
- [ ] Exposing infrastructure credentials or provider-native runtime fields to API clients.
- [ ] A React UI backend selector — the backend choice is available through the job request/configuration contract; a UI control is a separate product decision.
- [ ] A durable, stateful fair-share admission broker for `auto` routing — only added later if stateless weighted routing proves insufficient.
