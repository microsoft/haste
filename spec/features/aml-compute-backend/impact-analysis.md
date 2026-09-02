# Impact Analysis: Backend-neutral compute runner + Azure Machine Learning backend

## Scope of Change

### HASTE Components Affected

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core library — runner base | `hastelib/src/hastegeo/core/runners/base.py` | modified (contract replaced) | high |
| Core library — Batch adapter | `hastelib/src/hastegeo/core/runners/azure_batch.py` | modified (adapter split, finalize fix) | high |
| Core library — local adapter | `hastelib/src/hastegeo/core/runners/local.py` | modified (native `ComputeRunner`) | medium |
| Core library — unified runner | `hastelib/src/hastegeo/core/runners/unified_runner.py` | deprecated/replaced by registry + execution service | medium |
| Core library — new AML adapter | `hastelib/src/hastegeo/core/runners/azure_ml.py` | new | high |
| Core library — execution service/registry/router | `hastelib/src/hastegeo/core/runners/{execution_service,registry,router}.py` | new | high |
| Core library — compute models | `hastelib/src/hastegeo/core/models/compute.py` | new | high |
| Core library — job models | `hastelib/src/hastegeo/core/models/projects.py` | modified (additive `computeJob` field) | low |
| Core library — config | `hastelib/src/hastegeo/core/config.py` | modified (typed compute/AML config added) | medium |
| Core library — processors | `hastelib/src/hastegeo/core/processors/{train,inference,embedding,imagery,artifacts}.py` | modified (build specs, drop direct Batch config use) | high |
| REST API | `api/hastefuncapi/function_app.py` | modified (optional validated compute-selection field on existing launch requests) | low |
| Queue workers | `api/hastefuncqueues/function_app.py` | modified (dispatch by persisted handle) | medium |
| Docker config | `docker/training/scripts/set_dirs.sh`, `docker/imageryprep/scripts/set_dirs.sh`, `docker/training/code/run_workflow.py` | modified (`HASTE_JOB_WORKDIR` + legacy alias) | medium |
| Infrastructure | `infra/modules/aml{Workspace,Compute,Environment,Datastore,Role}.bicep`, `infra/main.bicep`, `infra/main.bicepparam`, `infra/modules/functions.bicep` | new + modified | high |
| Build | `hastelib/pyproject.toml`, Function app requirements, `env.yml` | modified (new optional `azure-ml` extra) | medium |
| CI/CD | `.github/workflows/*` | modified (dependency-drift + AML-extra test lane) | low |

## Azure Service Impact

| Service | Change | New Cost Impact |
|---|---|---|
| Azure Machine Learning | Stage 1: reference-only via `AML_MODE=Existing` — the operator-provided workspace, compute, environments, and datastore already exist; HASTE creates and mutates nothing. Optional `Create`-mode IaC (implemented in source, not applied this rollout) would additionally provision scale-to-zero GPU/CPU compute clusters, registered environments, and an identity-based datastore | None for Stage 1 (no new resources). If `Create` mode is ever applied under a separately approved future scenario, pay-per-use compute comparable to an equivalent Batch node cost would apply |
| Azure Batch | No topology change; adapter boundary only | None |
| Blob Storage | No new containers; `Existing`-mode AML datastore reference does not modify the existing account; `Create` mode (not applied) would register identity-based access | None |
| Azure Functions (`api`, `queues`) | Optional `azure-ai-ml==1.34.1` dependency (approved, pinned), lazily imported. No new RBAC granted in Stage 1 — `Existing` mode is pure reference, so the operator grants the Function identity whatever AML/ACR/storage access it decides to allow, outside of HASTE's IaC; `Create` mode (not applied) would add HASTE-managed least-privilege RBAC | Negligible (no new compute; cold-start impact only when the AML SDK is actually imported) |
| Cosmos DB | Additive optional field on four existing document types; no new container, no RU-tier change expected | Negligible |
| Managed Identity | No new identity created for Stage 1 (`Existing` mode references whatever identity the operator already granted access outside of HASTE's IaC). `Create` mode (not applied) would grant the existing queue Function App identity the *AzureML Data Scientist* role via `amlRole.bicep` (or a dedicated user-assigned managed identity when `AML_IDENTITY_MODE=managed`); ACR pull for the registered environment image continues to use the existing shared `acrRole` grant Batch already relies on | None |

> Static Web Apps, Data Lake, Queue Storage message schema, and TiTiler: no
> change.

## Dependency Analysis

### Upstream Dependencies (things this feature needs)

| Dependency | Type | Status | Risk if Unavailable |
|---|---|---|---|
| `azure-ai-ml` SDK v2 + `azure-identity` | library | approved and pinned: `azure-ai-ml==1.34.1` (+ `azure-identity`); dependency review by `security` complete | AML adapter cannot be implemented without it; feature degrades to Batch/local only (acceptable — AML remains optional) |
| AML workspace/compute/environment/datastore (per `AML_MODE`) | infra | operator-provided; `Existing`-mode reference implemented (no HASTE-managed provisioning in this rollout); optional `Create`-mode IaC implemented in source but not applied | AML backend unavailable; `auto` and explicit `azure_ml` requests fail with a classified configuration error, Batch/local continue unaffected |
| Existing ACR image tags/digests (Batch's current images) | build artifact | available | AML environment registration blocked without a stable image reference to bind to |
| `batch-compute-expansion` managed-identity/SAS conventions | spec/pattern | available (in-progress spec) | Batch adapter split must not regress isolation guarantees already shipped there |
| Operator confirmation of the existing AML workspace, compute, datastore, and identity to reference | operator decision | required before enabling `Existing` mode for a given deployment; not gated by HASTE IaC changes since Stage 1 performs no deployment operation | AML backend unavailable for that deployment until the operator supplies valid references |

### Downstream Impact (things affected by this feature)

| Consumer | How Affected | Breaking? | Migration Needed? |
|---|---|---|---|
| Existing Batch-only deployments | New optional config, additive `computeJob` field, deprecated `RUNNER_TYPE` alias | no | no — all new behavior defaults to current Batch behavior |
| `UnifiedRunner`/`BaseRunner` direct consumers (if any exist outside the five processors) | Contract replaced; deprecated `(job_id, task_id)` wrappers kept for one release | yes, after the deprecation window | yes — must migrate to `ComputeRunner`/`ComputeExecutionService` before wrappers are removed |
| `TrainingJob`/`InferenceJob`/`ImageryPreprocessJob`/`ZipJob` API consumers | Optional new `computeJob` field in responses | no | no — additive, ignorable by existing clients |
| Docker training/imageryprep images already published | Must keep working via legacy `AZ_BATCH_*` aliases exported by adapters | no | no immediate rebuild required; new images should adopt `HASTE_JOB_WORKDIR` |
| `docs/configuration.md`, `docs/architecture.md` | New settings and runner architecture documented | no | docs update in progress (tracked in [plan.md](plan.md)) |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| Duplicate GPU job submitted on retry/race | Low | High | Deterministic `executionId`-derived provider job name; idempotent get-or-create submit; reconciliation instead of blind retry | backend-dev |
| Wrong backend addressed after config change or worker restart | Medium | High | Backend/provider handle persisted on the job record; lifecycle dispatch always reads the persisted handle, never the process-global default | backend-dev |
| AML adapter forces Batch/local-only deployments to pay SDK import/startup cost | Medium | Medium | Lazy adapter import via `RunnerRegistry`; `azure-ai-ml` behind an optional extra | backend-dev |
| Container image behaves differently on AML vs. Batch | Medium | High | Immutable AML environment versions bound to the same container image tag/digest Batch uses; end-to-end parity tests per workload | backend-dev, backend-validation |
| Standing secret introduced for AML auth | Low | Critical | `DefaultAzureCredential` only; no keys/passwords; security review of IaC and adapter code | security |
| Shared AML compute gains cross-deployment storage access | Low | Critical | Identity-based datastore access scoped per deployment; cross-deployment access-denied test required before `auto`/`azure_ml` GA | security, backend-dev |
| New Python dependency introduces an unpatched CVE or unmaintained transitive package | Medium | Medium | `security` audited `azure-ai-ml==1.34.1` and its transitive set; approved and pinned; `security-validation` confirmed the resolved lockfile | security, security-validation |
| `AZ_BATCH_*` removal breaks an already-published container image | Medium | Medium | Adapters keep exporting legacy variables through the compatibility window; no forced image rebuild | backend-dev |
| Bicep `Create`/`Existing`/`Disabled` templates drift or fail local compilation/static checks | Medium | Medium | Local Bicep compilation and static template review for all three modes before merge; no Azure deployment operation required for this rollout | backend-dev, backend-validation |
| `auto` routing produces uneven or surprising backend distribution | Medium | Low | Deterministic weighted rendezvous hashing with documented, testable routing-reason output; conservative default weights at rollout | backend-dev |

## Performance Impact

- **API latency:** Negligible — optional compute-selection field validated
  the same way as existing request fields; no new round trip on the request
  path.
- **Queue throughput:** Unchanged shape; processors now build a typed spec
  before submission, a pure in-process transformation.
- **Batch compute:** No change — Batch adapter preserves current submission
  and polling behavior exactly.
- **AML compute:** New cold-start latency for scale-to-zero clusters
  (comparable to Batch autoscale) and immutable-environment image resolution;
  mitigated with environment/image-digest caching and status states that
  distinguish `queued`/`preparing` from failure.
- **Storage I/O:** Unchanged volume and path; AML uses identity-based direct
  provider transfer, avoiding an extra Function-host copy, matching Batch's
  current behavior.
- **Tile serving:** No impact — TiTiler is untouched.

## Security Impact

- [x] New API endpoints exposed? — No new verb-style routes; existing launch
      endpoints gain one optional, validated field. Client-supplied
      `computeJob`/provider runtime state is explicitly rejected.
- [x] New data classification handled? — No new data classification; the same
      satellite imagery and model artifacts flow through a new compute
      backend.
- [ ] MSAL/Entra ID auth changes? — No.
- [x] New secrets or connection strings required? — No. AML auth uses
      `DefaultAzureCredential`; no account keys, passwords, or connection
      strings are added.
- [ ] CORS configuration changes in SWA? — No.
- [x] New federated credentials needed? — No new human-supplied secret in any
      case. Stage 1 (`Existing` mode) requires no new managed identity
      binding from HASTE — the operator grants access to whatever identity
      HASTE already runs as, outside of HASTE's IaC.
- [ ] New RBAC — Not in Stage 1: `Existing` mode assigns no RBAC role from
      HASTE IaC. `Create` mode (implemented in source as `amlRole.bicep`, not
      applied this rollout) would grant the queue Function App identity the
      built-in *AzureML Data Scientist* role (job submit/read/cancel, read
      compute — explicitly excluding workspace management and compute
      create/delete/listKeys), scoped to the AML workspace's resource group;
      ACR pull continues to use the existing shared `acrRole` grant Batch
      already relies on.

## Compliance & Data Impact

- [ ] Geospatial data sovereignty concerns? — No region change assumed; the
      deploying operator determines the tenant, subscription, region, and
      network placement of the existing AML workspace referenced in
      `Existing` mode — HASTE does not assume or require a particular
      placement.
- [x] Partner data sharing agreements affected? — Must be preserved: shared
      AML compute (if any) must not gain standing cross-deployment storage
      access, consistent with the `batch-compute-expansion` isolation
      guarantee.
- [ ] New data retention requirements? — No; AML run history retention follows
      platform-standard AML defaults and is not modified by HASTE.
- [x] Audit logging for new operations? — Yes; every submission/lifecycle
      call is logged with `executionId`, workload, backend, routing reason,
      and provider job ID (see [design.md](design.md#observability)).
- [x] Component Governance scan implications? — Yes; `azure-ai-ml==1.34.1`
      and `azure-identity` were scanned and approved through Component
      Governance / dependency review before pinning.

## Rollback Assessment

- **Reversibility:** fully reversible for application behavior. Stage 1
  (`AML_MODE=Existing`) creates no HASTE-managed AML resources, so there is
  nothing for HASTE to decommission. If a future, separately approved
  scenario applies `Create` mode, that infrastructure would require its own
  explicit, separate decommissioning after all AML job handles are terminal
  and retention requirements are met (not an application rollback step).
- **Cosmos data:** No rollback needed — `computeJob` is additive and ignored
  by prior code versions; legacy `jobId`/`taskId` remain authoritative
  throughout.
- **Blob data:** No cleanup needed — output paths and containers are
  unchanged by this feature.
- **API:** Backward-compatible — omitted compute-selection fields default to
  current Batch behavior; existing clients are unaffected.
- **Batch behavior:** Fully preserved behind the adapter boundary; Batch
  remains enabled throughout rollout (this feature adds AML, it does not
  replace Batch).
- **Estimated rollback time:** Application-level rollback (disable AML/`auto`
  submissions via configuration, or revert the deploy) is under 15 minutes,
  consistent with existing HASTE flag-based rollbacks. `Create`-mode
  infrastructure teardown, if that mode is ever applied under a separately
  approved future scenario, is a separate, deliberately slower operation
  gated on job/retention state (see [rollout.md](rollout.md)).
