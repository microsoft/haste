# ADR-0005: Backend-neutral compute runner and Azure Machine Learning as a backend

**Status:** accepted
**Date:** 2026-09-01
**Deciders:** HASTE engineering team

## Context

HASTE runs GPU/CPU workloads — training, inference, embedding, imagery
preprocessing, and artifact packaging — through
`hastelib/src/hastegeo/core/runners/`. `UnifiedRunner`
(`unified_runner.py`) is a two-entry factory that dynamically imports either
`AzureBatchRunner` or `LocalRunner`, both of which implement a Batch-shaped
`BaseRunner` contract: `add_task(job_id, task_id, ...)`,
`get_filecontent_from_task(job_id, task_id, ...)`, `get_task_status`,
`cancel_task`, `cleanup_task`. Every processor that submits compute
(`train.py`, `inference.py`, `embedding.py`, `imagery.py`, `artifacts.py`)
calls `Config.get_azure_batch_config()` directly, constructs commands around
`AZ_BATCH_TASK_WORKING_DIR`, and expects a `(job_id, task_id)` tuple back —
even when the selected runner is `local`. Persisted job records
(`TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`, `ZipJob` in
`hastegeo/core/models/projects.py`) store only Batch `jobId`/`taskId`, so
nothing records which backend a running job used; a `RUNNER_TYPE`
configuration change while jobs are in flight can route polling or
cancellation to the wrong provider.

HASTE has been asked to run compute on Azure Machine Learning (AML) in
addition to Azure Batch. This is an architecture change to the compute layer
referenced in `spec/architecture/overview.md`, and the full scope, options,
and consequences are detailed in `spec/features/aml-compute-backend/`. This
ADR records the two decisions with system-wide, hard-to-reverse
consequences: (1) how the runner boundary is shaped, and (2) how Azure
Machine Learning is introduced as a backend.

## Options Considered

### Option A: Add `AzureMLRunner` behind the current Batch-shaped `BaseRunner`

- **Pros:** Smallest immediate diff; no processor changes required.
- **Cons:** Preserves the exact coupling that motivates this ADR. AML would
  have to fabricate a `(job_id, task_id)` pair, invent a `Batch`-shaped
  polling model it doesn't naturally have, and every future backend would
  repeat the same emulation. Persisted identifiers remain documented as
  "Azure Batch identifiers" even when they aren't.
- **Impact on HASTE components:** `runners/azure_ml.py` added, but
  `base.py`, processors, and job models are untouched — the coupling this ADR
  exists to remove is left in place.

### Option B: Wrap the current keyword-dictionary contract in a thin adapter

- **Pros:** Reduces processor edits relative to Option C.
- **Cons:** Leaves untyped provider concepts, `AZ_BATCH_*` work-directory
  variables, and ambiguous lifecycle semantics (what does "cancel" mean when
  a job has already finished on the provider?) unresolved. Validation of
  paths, URIs, and secrets stays ad hoc per call site instead of centralized.
- **Impact on HASTE components:** Marginal improvement to `runners/`; no
  structural change to processors or job models.

### Option C: Introduce typed `ComputeJobSpec` and `ComputeJobHandle` contracts — **Chosen**

- **Pros:** Every backend receives the same logical inputs, outputs,
  resources, status, and lifecycle. Validation (path traversal, URI schemes,
  image/environment immutability rules, secret exclusion) is centralized and
  tested once in `hastegeo.core.models.compute`. A persisted
  `ComputeJobHandle` makes backend/provider identity stable across restarts
  and configuration changes, closing the `RUNNER_TYPE`-drift problem
  described above. Adding a third or fourth backend later (Kubernetes, a
  different managed compute service) requires implementing one interface,
  not reverse-engineering
  Batch's job/task model.
- **Cons:** Requires a controlled, multi-phase migration of `base.py`, both
  existing adapters, five processors, and four job models, plus
  characterization tests to prove no behavior regression during the
  migration (see `spec/features/aml-compute-backend/plan.md`).
- **Impact on HASTE components:** New `hastegeo/core/models/compute.py`;
  `runners/base.py` contract replaced; `runners/azure_batch.py` and
  `runners/local.py` migrated to adapters; new `runners/azure_ml.py`,
  `runners/execution_service.py`, `runners/registry.py`, `runners/router.py`;
  `models/projects.py` gains an additive `computeJob` field; all five
  processors migrated to build specs instead of reading Batch config
  directly.

### Backend-introduction sub-decision: how AML resources are owned

For provisioning AML itself, three sub-options were considered — reference
only an existing workspace; always create a workspace and compute with
HASTE; or mirror the Batch `Create`/`Existing` pattern (established in
`batch-compute-expansion`) and also permit `Disabled`. The third was chosen:
it supports both self-contained deployments and shared platform deployments
without forcing one ownership model, and keeps the deployment-mode vocabulary
consistent between Batch and AML.

## Decision

Adopt **Option C**: replace the Batch-shaped `BaseRunner` contract with a
typed, backend-neutral `ComputeRunner` interface
(`validate`/`submit`/`get_status`/`read_output`/`cancel`/`finalize`/
`get_capacity`) operating on `ComputeJobSpec` and `ComputeJobHandle`. Azure
Batch and local Docker execution are migrated to implement this interface as
adapters with no behavior change to their existing users. Azure Machine
Learning is introduced as a third adapter implementing the same interface via
`azure-ai-ml==1.34.1` (SDK v2, approved and pinned after `security` review)
command jobs, using `DefaultAzureCredential` and no standing secrets. AML
infrastructure supports `Disabled`, `Create`, and `Existing` modes, mirroring
the Batch `Create`/`Existing` convention.

Adoption is staged: the initial rollout applies only `Existing` mode as a
pure reference to an operator-provided AML workspace, compute, environment(s),
datastore, and identity — HASTE creates no AML resource and assigns no RBAC
role in this stage; the operator grants the identity HASTE runs as whatever
access it decides to allow, outside of HASTE's IaC. `Create` mode (which
would additionally provision resources and least-privilege RBAC) is
implemented in source and verified with local Bicep compilation and static
template checks, but is not applied until a separately approved future
scenario adopts it.

Backend selection is per-job (`azure_batch`, `azure_ml`, `local`, or `auto`),
not a single global switch, with the requested and selected backend and
provider handle persisted on the job record so lifecycle operations remain
stable across restarts and configuration changes. `auto` uses a stateless,
deterministic weighted-rendezvous router over adapter-reported
capability/capacity snapshots rather than a new durable scheduling service —
consistent with the project's preference for systems over new high-blast-
radius services.

Full behavioral detail — routing resolution order, idempotent submission,
work-directory contract (`HASTE_JOB_WORKDIR` plus legacy `AZ_BATCH_*`
aliases), workload migration matrix, and edge-case handling — is specified in
`spec/features/aml-compute-backend/design.md` and is binding alongside this
ADR.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Runner contract | `hastelib/src/hastegeo/core/runners/base.py` | Replaced with `ComputeRunner`; deprecated `(job_id, task_id)` wrappers kept for one release |
| Batch adapter | `hastelib/src/hastegeo/core/runners/azure_batch.py` | Migrated to implement `ComputeRunner`; existing routing/SAS behavior preserved |
| Local adapter | `hastelib/src/hastegeo/core/runners/local.py` | Migrated to implement `ComputeRunner` natively; Batch emulation becomes internal only |
| AML adapter (new) | `hastelib/src/hastegeo/core/runners/azure_ml.py` | New adapter using `azure-ai-ml==1.34.1` (SDK v2, approved and pinned) |
| Execution service, registry, router (new) | `hastelib/src/hastegeo/core/runners/{execution_service,registry,router}.py` | New orchestration seam replacing the two-entry `UnifiedRunner` factory |
| Compute models (new) | `hastelib/src/hastegeo/core/models/compute.py` | `ComputeJobSpec`, `ComputeJobHandle`, enums, capacity models, typed exceptions |
| Job models | `hastelib/src/hastegeo/core/models/projects.py` | Additive `computeJob: Optional[ComputeJobHandle]` on `TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`, `ZipJob` |
| Processors | `hastelib/src/hastegeo/core/processors/{train,inference,embedding,imagery,artifacts}.py` | Build `ComputeJobSpec`; no direct `get_azure_batch_config()`/`AZ_BATCH_*` use |
| Config | `hastelib/src/hastegeo/core/config.py` | Typed compute/AML configuration; `RUNNER_TYPE` becomes a deprecated alias |
| Infrastructure | `infra/modules/aml{Workspace,Compute,Environment,Datastore}.bicep`, `infra/main.bicep`, `infra/main.bicepparam` | New `Disabled`/`Create`/`Existing` AML modes. `Existing` is applied for the Stage 1 rollout as a pure reference (no resource creation, no RBAC); `Create` compiles locally but is not applied until a separately approved future scenario |

### Azure Services Affected

| Service | Change |
|---|---|
| Azure Machine Learning | Stage 1: referenced via `AML_MODE=Existing` (operator-provided workspace, compute, environment(s), datastore — HASTE creates nothing). Optional `Create` mode (not applied this rollout) would additionally provision scale-to-zero GPU/CPU compute clusters, immutable environment versions bound to the same container image tag/digest Batch uses, and an identity-based datastore |
| Azure Batch | No topology change; execution moves behind an adapter boundary with identical behavior |
| Azure Functions (`api`, `queues`) | New optional `azure-ai-ml==1.34.1` dependency (approved, pinned), lazily imported; no new RBAC in Stage 1 (`Existing` mode is pure reference — the operator grants access outside HASTE's IaC). `Create` mode (not applied) would deploy `amlRole.bicep`, granting the queue Function App identity the AzureML Data Scientist role (job submit/read/cancel, read compute); ACR pull continues to use the existing shared `acrRole` grant Batch already relies on |

## Consequences

- **Easier:** Adding a future compute backend requires implementing one typed
  interface, not reverse-engineering Batch's job/task model. Backend/provider
  identity is stable across restarts and configuration changes. Path/URI/
  secret validation is centralized and tested once instead of duplicated per
  adapter.
- **Harder:** The migration touches five processors, four job models, and two
  existing adapters, and requires characterization tests up front to prove no
  regression — this is explicitly a multi-phase effort (see
  `spec/features/aml-compute-backend/plan.md`), not a small patch.
- **New constraints:** All compute submission must go through
  `ComputeExecutionService`; no processor may call
  `Config.get_azure_batch_config()` or reference `AZ_BATCH_*` directly once
  migration completes. New backends must report capability/capacity snapshots
  to participate in `auto` routing. AML configuration is validated only when
  AML is enabled or explicitly selected, so Batch/local-only deployments never
  import or initialize the AML SDK.
- **Impact on Docker Compose local dev stack:** None structurally — the
  local adapter continues to back the Docker Compose dev stack; its public
  surface changes to `ComputeRunner`, with Batch-variable emulation moved
  inside the adapter.
- **Impact on CI/CD workflows:** New dependency-drift and optional
  AML-extra test lanes are added. Local Bicep compilation and static
  template checks cover `Disabled`/`Create`/`Existing` AML modes; no Azure
  deployment operation is part of CI/CD for the initial `Existing`-mode
  rollout, and `Create`-mode deployment is deferred to a separately approved
  future scenario.
