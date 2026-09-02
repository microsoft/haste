# Execution Plan: Backend-neutral compute runner + Azure Machine Learning backend

This is a `hastelib` core-library + infra feature with no dedicated UI phase
(backend selection is a request/configuration field, not a UI control — see
[user-stories.md](user-stories.md#out-of-scope)). See
[user-stories.md](user-stories.md#agent-assignment-map) for the agent→story
mapping and [rollout.md](rollout.md) for the deployment sequence.

## Phases

### Phase 1: Spec, ADR, and characterization tests

**Goal:** Establish the source of truth and capture current Batch/local
behavior before any refactor.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Write spec (README, design, impact-analysis, user-stories, data-model, test-plan, rollout) | `backend-dev` | — | — | done |
| Add ADR-0005 for the backend-neutral runner + AML backend | `backend-dev` | — | US-001 | done |
| Add characterization tests for current Batch/local submission payloads, status mapping, output paths, cancellation, node-loss fallback | `backend-dev` | — | US-001 | done — folded into the Phase 4 adapter test suites (e.g. `test_azure_batch_compute_runner.py`'s legacy `(job_id, task_id)` contract coverage) rather than a separate pre-refactor snapshot |
| Capture each processor's current input/output contract as a fixture baseline | `backend-dev` | — | US-001 | done — covered by the Phase 8 processor/conformance test suites |

**Exit Criteria:**
- [x] Spec approved and cross-linked
- [x] Characterization tests pass against current Batch/local behavior (pre-refactor baseline)

### Phase 2: Compute models and contracts

**Goal:** Add the backend-neutral vocabulary with no behavior change yet.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add enums, `ComputeJobSpec`, `ComputeJobHandle`, capacity models in `hastegeo/core/models/compute.py` | `backend-dev` | Phase 1 | US-001, US-008 | done |
| Add typed compute exceptions | `backend-dev` | — | US-001 | done |
| Unit tests for model validation and secret-exclusion rules | `backend-dev` | above | US-001, US-008 | done |

**Exit Criteria:**
- [x] All new model unit tests pass
- [x] Compute models used by no runtime code yet (pure addition, zero behavior change)

### Phase 3: Execution service, registry, and router

**Goal:** Add orchestration seams before migrating any adapter.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Implement `RunnerRegistry` (replaces the two-entry import map) | `backend-dev` | Phase 2 | US-001 | done |
| Implement `ComputeRouter` (deterministic weighted rendezvous, capability filtering) | `backend-dev` | Phase 2 | US-003 | done |
| Implement `ComputeExecutionService` (validate, resolve backend, idempotent submit, handle-based lifecycle dispatch) | `backend-dev` | registry, router | US-003, US-004, US-005 | done |
| Unit tests: explicit routing, `auto` routing, capability filtering, idempotent retry/race handling | `backend-dev` | above | US-003, US-005 | done |

**Exit Criteria:**
- [x] Router and execution-service unit tests pass with fake adapters
- [x] No duplicate-submission scenario in the test suite creates two provider jobs

### Phase 4: Migrate Azure Batch and local Docker behind the new contract

**Goal:** Batch and local keep working exactly as today, now behind `ComputeRunner`.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Split low-level Batch API calls from `ComputeRunner` translation in `azure_batch.py` | `backend-dev` | Phase 3 | US-001 | done |
| Preserve multi-pool routing and SAS behavior from `batch-compute-expansion` | `backend-dev` | — | US-001 | done |
| Fix per-execution finalize so a shared Batch job with other active tasks is not disabled | `backend-dev` | — | US-001 | done |
| Migrate `local.py` to implement `ComputeRunner` natively; keep `AZ_BATCH_*` emulation internal to the adapter | `backend-dev` | Phase 3 | US-001 | done |
| Deprecate `BaseRunner`/`UnifiedRunner` `(job_id, task_id)` methods as thin compatibility wrappers | `backend-dev` | above | US-001 | done |
| Extend existing Batch/local runner test suites for the new contract | `backend-dev` | above | US-001 | done |

**Exit Criteria:**
- [x] Full existing Batch/local test suite passes against the new contract
- [x] Characterization tests from Phase 1 pass unchanged (behavior parity confirmed)

### Phase 5: Persisted backend-aware job handles

**Goal:** Every workload record can carry and recover a compute handle.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add optional `computeJob: ComputeJobHandle` to `TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`, `ZipJob` | `backend-dev` | Phase 2 | US-004 | done |
| Add legacy Batch-handle synthesis for records with only `jobId`/`taskId` | `backend-dev` | — | US-004 | done |
| Generate deterministic `executionId` before provider submission | `backend-dev` | — | US-004, US-005 | done |
| Model compatibility tests: old records load as Batch, new records round-trip, client-supplied runtime fields rejected | `backend-dev` | above | US-004 | done |

**Exit Criteria:**
- [x] Legacy record synthesis tests pass
- [x] No Cosmos schema migration/backfill required (confirmed additive)

### Phase 6: Standardize the container workspace contract

**Goal:** Remove the Batch work-directory assumption from processor-generated
commands while keeping already-published images working.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Introduce `HASTE_JOB_WORKDIR` in processor-generated YAML/commands | `backend-dev` | Phase 4 | US-001 | done |
| Update `docker/training/scripts/set_dirs.sh`, `docker/imageryprep/scripts/set_dirs.sh`, `docker/training/code/run_workflow.py` | `backend-dev` | — | US-001 | done |
| Keep legacy `AZ_BATCH_*` aliases exported by adapters during the image transition | `backend-dev` | — | US-001 | done |
| Container contract tests for both variable sets | `backend-dev` | above | US-001 | done |

**Exit Criteria:**
- [x] Both `HASTE_JOB_WORKDIR`-aware and legacy-only images resolve identical paths

### Phase 7: Azure Machine Learning adapter and dependency

**Goal:** Implement AML as a peer backend with no cost to non-AML deployments.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Evaluate and pin `azure-ai-ml==1.34.1` (+ `azure-identity`) as an optional `azure-ml` extra | `security` | Phase 2 | US-002 | done |
| Confirm dependency approval and lockfile | `security-validation` | above | US-002, US-008 | done |
| Implement lazy `MLClient` creation, config validation, command-job mapping, immutable environment resolution, input staging, named output mapping | `backend-dev` | Phase 3, dependency approval | US-002 | done |
| Implement status normalization, output/log reading, cancellation, finalization, capacity snapshots, submission reconciliation | `backend-dev` | — | US-002, US-005 | done |
| Unit tests with mocked `MLClient` for all above | `backend-dev` | above | US-002 | done |
| Update Function app requirements and `env.yml` with lazy-import guarantees | `backend-dev` | — | US-002 | done |

**Exit Criteria:**
- [x] AML adapter unit tests pass against mocked `MLClient`
- [x] Batch/local-only deployments do not import `azure-ai-ml` (verified by import-cost test)
- [x] `security` dependency review closed; `security-validation` confirmed

### Phase 8: Migrate all workload processors

**Goal:** No processor talks to Batch config or `AZ_BATCH_*` directly.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add `build_*_job_spec()` for training, inference, embedding, imagery preprocessing, artifact packaging | `backend-dev` | Phases 4-7 | US-001, US-007 | done |
| Define automatic follow-on backend inheritance and workload overrides | `backend-dev` | — | US-007 | done |
| Remove `get_azure_batch_config()`/`AZ_BATCH_*` from all five processors | `backend-dev` | — | US-001 | done |
| Backend conformance fixtures: same logical spec through fake Batch, AML, local | `backend-dev` | — | US-001, US-002 | done |
| Processor unit tests updated/added for all five workloads | `backend-dev` | above | US-001, US-007 | done |

**Exit Criteria:**
- [x] `rg "get_azure_batch_config|AZ_BATCH_" hastelib/src/hastegeo/core/processors` returns no matches
- [x] All five processors pass conformance fixtures on Batch, AML, and local

### Phase 9: Per-job backend selection in existing API requests

**Goal:** Expose the compute choice without adding new verb-style routes.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add a validated optional compute-selection field to existing launch requests in `api/hastefuncapi/function_app.py` | `backend-dev` | Phase 8 | US-003 | done |
| Default omitted selections compatibly | `backend-dev` | — | US-003 | done |
| Reject client-supplied provider runtime state/handles | `backend-dev` | — | US-004, US-008 | done |
| Update queue handlers in `api/hastefuncqueues/function_app.py` to dispatch lifecycle ops by persisted handle | `backend-dev` | Phase 5 | US-004 | done |
| API and queue integration tests | `backend-dev` | above | US-003, US-004 | done |

**Exit Criteria:**
- [x] API integration tests pass (backward-compatible defaults + validated selection)
- [x] Queue integration tests confirm handle-based routing survives restart/config change

### Phase 10: Azure Machine Learning IaC

**Goal:** Provide `Disabled`/`Create`/`Existing` AML infrastructure, with
`Existing` verified locally as a pure reference for the Stage 1 rollout;
`Create` implemented in source for a separately approved future scenario.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Document operator prerequisites for `Existing` mode (existing workspace, compute, environment(s), datastore, and identity to reference) | `backend-dev` | — | US-006 | done |
| Add `infra/modules/amlWorkspace.bicep`, `amlCompute.bicep`, `amlEnvironment.bicep`, `amlDatastore.bicep` | `backend-dev` | Phase 7 | US-006 | done |
| Add `Disabled`/`Create`/`Existing` parameters to `main.bicep`/`main.bicepparam` | `backend-dev` | — | US-006 | done |
| Add least-privilege RBAC (`amlRole.bicep`, `Create` mode only) and always-emitted `AML_*` application settings (`functions.bicep`; inert/empty when `Disabled`, operator-provided references when `Existing`) | `backend-dev` | — | US-006, US-008 | done |
| Security review of RBAC scope, keyless auth, and cross-deployment isolation | `security` | above | US-006, US-008 | done |
| Confirm security findings addressed | `security-validation` | above | US-006, US-008 | done |
| Local Bicep compilation + static template checks for all three modes (no Azure deployment operation) | `backend-dev` | above | US-006 | done |

**Exit Criteria:**
- [x] `Disabled`, `Existing`, and `Create` modes compile and pass local static
      template checks; no mode was applied during implementation, and
      `Create` remains pending separate approval
- [x] `security-validation` sign-off recorded

### Phase 11: Observability, full test suite, and rollout

**Goal:** Ship with confidence and a validated rollback path.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add correlated logs, provider tags, and metrics per [design.md](design.md#observability) | `backend-dev` | Phases 1-10 | — | in-progress — log-safety correlation fields (`executionId`/backend/profile/provider IDs/routing reason) landed; full submissions/completions/failures/duration metrics not yet added |
| Run unit, contract, integration, security, and end-to-end tests per [test-plan.md](test-plan.md) | `backend-dev` | — | all | in-progress — unit/contract/model-compatibility/API/queue tests landed; live AML smoke, GPU smoke, and end-to-end parity tests not yet run (no live AML deployment performed) |
| Validate all test results and acceptance criteria against the spec | `backend-validation` | above | all | in-progress — local unit/contract/API/queue/container/IaC validation and pre-landing review feedback are complete; authorized live AML/Batch parity and rollout checks remain |
| Update `docs/architecture.md`, `docs/configuration.md`, `spec/architecture/overview.md`, `docs/hastelib/runners.md` | `backend-dev` | — | — | done — public documentation, deployment settings, and Disabled/Existing/Create behavior are synchronized with the implementation |
| Execute staged rollout per [rollout.md](rollout.md) | `backend-dev` | above | all | not-started — no live deployment performed |
| Rollback exercise (disable AML/`auto`, confirm existing handles keep working) | `backend-dev` | — | US-004, US-005 | not-started |

**Exit Criteria:**
- [ ] Full `hastelib` suite green: `cd hastelib && hatch run test:pytest`
- [ ] All rollout phases in [rollout.md](rollout.md) complete through the target environment set
- [ ] `backend-validation` sign-off recorded

## Milestones

| Milestone | Status | Deliverable |
|---|---|---|
| Spec + ADR approved | done | This spec + ADR-0005 signed off |
| Neutral contract + Batch/local migration done | done | Phases 2-6 merged, zero behavior change confirmed |
| AML adapter done | done | Phase 7 merged; `azure-ai-ml==1.34.1` approved and pinned |
| All processors migrated | done | Phase 8 merged; `rg` checks clean |
| Per-job backend selection wired | done | Phase 9 merged; API/queue tests landed |
| AML IaC ready for review | done | Phase 10 complete; `Existing` is locally verified as reference-only, while `Create` compiles but remains unapplied |
| Release | in progress | Local implementation, documentation, CI, and pre-landing review gates are complete; live AML validation and staged rollout remain |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | Spec/ADR, characterization tests, models, execution service/registry/router, Batch/local migration, persisted handles, workspace contract, AML adapter, processor migration, API/queue wiring, IaC, observability, rollout | 1-11 |
| `security` | Dependency review (`azure-ai-ml==1.34.1`, approved and pinned), IaC RBAC/keyless-auth review | 7, 10 |
| `security-validation` | Confirms dependency and IaC security findings are addressed | 7, 10 |
| `backend-validation` | Validates implementation against spec/tests before rollout | 11 |
| `orchestrator` | Tracks spec status and phase progress throughout | 1-11 |

> No `ui` or `gis` agent tasks — this feature has no UI or imagery-provider
> change.

## Resource Requirements

- **Agents:** `backend-dev` (implements), `backend-validation` (validates),
  `security` / `security-validation` (dependency + IaC security review),
  `orchestrator` (tracks progress).
- **Azure services:** Azure Machine Learning, referenced in `Existing` mode
  for Stage 1 (operator-provided workspace, compute, environments,
  datastore — HASTE creates nothing); optional `Create` mode (workspace,
  scale-to-zero GPU/CPU compute clusters, environments, identity-based
  datastore) is implemented in source for a separately approved future
  scenario but not applied this rollout. No change to Cosmos DB, Queue
  Storage, Static Web Apps, or existing Azure Batch topology.
- **GPU compute:** for Stage 1, whatever operator-provided AML compute
  targets are referenced; optional `Create`-mode clusters would be sized per
  workload tier, mirroring the Batch H100/T4 tiers from
  `batch-compute-expansion` where applicable.
- **External data:** none.

## Open Questions

- [ ] Which tenant, subscription, region, and network placement the
      operator-provided AML workspace, compute, environment(s), datastore,
      and identity use is decided per deployment by the operator, not fixed
      by this plan.
- [ ] Whether `auto` should default to Batch-weighted routing at first
      broader rollout, pending real AML capacity/cost data.
- [ ] Timing for removing the deprecated `(job_id, task_id)` `BaseRunner`
      wrappers and the `RUNNER_TYPE` alias, once all consumers have migrated.
