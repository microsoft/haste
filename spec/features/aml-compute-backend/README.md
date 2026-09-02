# Feature: Backend-neutral compute runner + Azure Machine Learning backend

**Status:** in-progress
**Author:** HASTE engineering team
**Date:** 2026-09-01
**Target Release:** TBD
**Priority:** P1
**Work Item:** TBD

## Summary

Replace HASTE's Batch-shaped `UnifiedRunner`/`BaseRunner` contract with a
typed, backend-neutral compute runner interface (`ComputeJobSpec` /
`ComputeJobHandle`), keep Azure Batch and local Docker execution behind
adapters that implement that interface, and add an Azure Machine Learning
(AML) command-job adapter with equivalent submit/status/output/log/cancel/
finalize behavior. Every current compute workload — training, inference,
embedding, imagery preprocessing, and artifact packaging — moves onto the
neutral contract. Each job can request `azure_batch`, `azure_ml`, `local`, or
`auto`; the resolved backend and provider handle are persisted with the job so
later queue invocations always address the correct provider.

This is the full feature, not an MVP: no current workload or lifecycle
operation (submit, poll, read output/logs, cancel, finalize) is deferred to a
later phase.

## Motivation

- `UnifiedRunner` is a two-entry Batch/local factory, not an abstraction. Its
  public methods (`add_task(job_id, task_id, ...)`,
  `get_filecontent_from_task`, `cancel_task`) expose Batch's job/task
  hierarchy, not a HASTE execution concept.
- Every processor (`train.py`, `inference.py`, `embedding.py`, `imagery.py`,
  `artifacts.py`) calls `Config.get_azure_batch_config()` directly and builds
  commands around `AZ_BATCH_TASK_WORKING_DIR`, even when running locally.
  Adding AML behind the same interface would force it to emulate Batch rather
  than be a peer backend.
- Persisted job records (`TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`,
  `ZipJob`) store only Batch `jobId`/`taskId`. Nothing records which backend a
  running job used, so a configuration change while jobs are in flight can
  route polling/cancellation to the wrong provider.
- This request asks HASTE to support running GPU compute on Azure Machine
  Learning. Doing that correctly requires the runner boundary to represent a
  HASTE execution rather than a Batch task — otherwise every future backend
  keeps re-implementing Batch's shape.
- If we don't build this: AML can only be bolted on as an `AzureMLRunner` that
  fakes Batch's `(job_id, task_id)` contract, which this feature's
  [ADR-0005](../../architecture/decisions/0005-backend-neutral-compute-runner-and-aml-backend.md)
  explicitly rejects.

## Success Criteria

- [ ] Every processor builds a `ComputeJobSpec` and contains no
      `Config.get_azure_batch_config()` call or `AZ_BATCH_*` work-directory
      dependency (`rg "get_azure_batch_config|AZ_BATCH_"
      hastelib/src/hastegeo/core/processors` returns no matches).
- [ ] The same HASTE deployment can run concurrent jobs on Batch and AML and
      keep polling/cancelling both after a Function worker restart or a
      `COMPUTE_BACKEND_DEFAULT` change.
- [ ] Training, inference, embedding, imagery preprocessing, and artifact
      packaging produce the same persisted HASTE artifacts and status
      transitions on Batch, AML, and local Docker.
- [ ] Explicit `azure_batch`/`azure_ml`/`local` requests are honored; `auto`
      distributes eligible jobs across configured healthy backends and records
      why a backend was selected.
- [ ] A provider submission retry never creates a duplicate compute run for the
      same `executionId`.
- [ ] Legacy records containing only `jobId`/`taskId` keep working as
      synthesized Azure Batch handles.
- [ ] `Existing` mode references an operator-provided AML workspace,
      compute, environment(s), datastore, and identity as a pure reference:
      HASTE creates no AML resources and assigns no RBAC roles. Optional
      `Create`-mode IaC compiles locally and is available in source for a
      separately approved future scenario, but is not applied during this
      rollout.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/models/` | New `compute.py` module: `ComputeJobSpec`, `ComputeJobHandle`, enums, capacity/status models, exceptions |
| `hastelib/src/hastegeo/core/runners/` | `base.py` contract replaced; `azure_batch.py`, `local.py` become adapters; new `azure_ml.py` adapter; new registry/router/execution-service modules |
| `hastelib/src/hastegeo/core/processors/` | `train.py`, `inference.py`, `embedding.py`, `imagery.py`, `artifacts.py` build specs and operate on handles instead of Batch config |
| `hastelib/src/hastegeo/core/models/projects.py` | Optional `computeJob` handle added to `TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`, `ZipJob` alongside legacy `jobId`/`taskId` |
| `hastelib/src/hastegeo/core/config.py` | Typed compute configuration (`COMPUTE_BACKEND_*`, AML settings model) alongside existing Batch config |
| `api/hastefuncapi/` | Optional, validated per-job compute-backend selection on existing launch requests (no new verb-style routes) |
| `api/hastefuncqueues/` | Queue handlers route lifecycle operations by persisted handle instead of the process-global runner type |
| `docker/training/scripts/set_dirs.sh`, `docker/imageryprep/scripts/set_dirs.sh`, `docker/training/code/run_workflow.py` | `HASTE_JOB_WORKDIR` becomes the primary workspace variable; `AZ_BATCH_*` kept as adapter-supplied legacy aliases during the image transition |
| `infra/` | New `amlWorkspace.bicep`, `amlCompute.bicep`, `amlEnvironment.bicep`, `amlDatastore.bicep`; `main.bicep`/`main.bicepparam` gain `Disabled`/`Create`/`Existing` AML modes. Stage 1 rollout uses `Existing` (pure reference via app settings only — no resource creation, no RBAC); optional `Create` mode (resource creation + least-privilege RBAC) compiles locally but is not applied this rollout |
| `hastelib/pyproject.toml`, Function app requirements, `env.yml` | Optional `azure-ml` extra with `azure-ai-ml==1.34.1` approved and pinned (lazily imported) |

## Related Specs

| Spec | Relationship |
|---|---|
| [batch-compute-expansion](../batch-compute-expansion/README.md) | Establishes managed identity, candidate compute targets, scale-to-zero, and tenant-isolation principles this feature must preserve on the Batch adapter; this feature does not change Batch pool topology |
| [infra-iac-migration](../infra-iac-migration/README.md) | Owns the Bicep/azd conventions this feature's new AML modules follow |
| [batch-node-loss-resilience](../batch-node-loss-resilience/README.md) | Batch-specific output-fallback behavior that must be preserved unchanged behind the neutral contract |
| [batch-config-drift](../batch-config-drift/README.md) | Batch configuration validation this feature must not regress while introducing typed compute configuration |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [plan.md](plan.md) | Execution plan: phases, milestones, agent summary | approved |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius, security | approved |
| [user-stories.md](user-stories.md) | User stories & acceptance criteria | approved |
| [design.md](design.md) | Technical design: contracts, routing, lifecycle, IaC, security | approved |
| [data-model.md](data-model.md) | Compute model schema, job-record, and configuration changes | approved |
| [test-plan.md](test-plan.md) | Test strategy & coverage matrix | approved |
| [rollout.md](rollout.md) | Rollout phases, flags, rollback | approved |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-01 | Introduce typed `ComputeJobSpec`/`ComputeJobHandle` contracts rather than an `AzureMLRunner` behind the current Batch-shaped methods | Prevents every future backend from having to emulate Batch; see [ADR-0005](../../architecture/decisions/0005-backend-neutral-compute-runner-and-aml-backend.md) |
| 2026-09-01 | Backend preference lives on every `ComputeJobSpec` (`azure_batch`, `azure_ml`, `local`, `auto`), not one global switch | Supports mixed Batch/AML deployments and per-job overrides without stranding in-flight jobs on a config change |
| 2026-09-01 | `auto` uses a stateless, deterministic weighted-rendezvous router over capability/capacity snapshots, not a durable scheduler service | Avoids a new high-blast-radius service while keeping retries pinned to the same backend |
| 2026-09-01 | Stage 1 rollout uses `AML_MODE=Existing` as a pure reference to an operator-provided AML workspace/compute/environment/datastore/identity — no HASTE-created resources and no RBAC assignment; verified with local Bicep compilation/static template checks, not an Azure deployment operation | HASTE must integrate with operator-managed assets first without provisioning or granting access to AML during initial enablement; optional `Create`-mode IaC remains available in source for a separately approved future scenario |
| 2026-09-01 | Pin `azure-ai-ml==1.34.1` as the approved AML SDK dependency | `security` completed dependency review; version approved and pinned for the AML adapter |
| 2026-09-01 | Persist requested + selected backend and provider handle on every job record | Makes lifecycle operations stable across restarts and configuration changes; required before AML can be introduced safely |
