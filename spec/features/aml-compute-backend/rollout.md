# Rollout Plan: Backend-neutral compute runner + Azure Machine Learning backend

## Rollout Strategy

**Type:** phased + feature-flag

Every new runtime behavior is behind configuration that defaults to current
Batch behavior. Shipping the neutral contract and Batch/local adapter
migration is a no-op for existing deployments until AML is explicitly
enabled — code rollout and behavior rollout are decoupled, consistent with
the `batch-compute-expansion` rollout pattern.

## Deployment Targets

Bicep (`infra/main.bicep` plus its modules) is the canonical, AML-capable
deployment path — it is the only path that wires the full `AML_*`
application-setting set and the `Create`-mode resource/RBAC modules. Legacy
setup scripts (`.github/scripts/deploy_apps.sh`, `setup/deploy_apps.sh`) are
gaining partial AML awareness incrementally (e.g. a `COMPUTE_BACKEND_DEFAULT`
setting), but do not yet wire the full `AML_*` setting set. Neither path
performs a live deployment as part of this rollout.

| Component | Deployment Method | Target |
|---|---|---|
| `hastelib` (compute models, execution service, registry, router, adapters) | Docker rebuild + Function App deploy (`azd deploy`) | `api` / `queues` Function Apps |
| Optional AML `Create`-mode resource IaC (`amlWorkspace.bicep`, `amlCompute.bicep`, `amlEnvironment.bicep`, `amlDatastore.bicep`) | Local Bicep compilation and static inspection only | Kept ready but not applied during this rollout |
| `functions.bicep` — `AML_*` application settings (always emitted; inert/empty when `Disabled`, populated with operator-provided references when `Existing`) | `azd provision` | `api` / `queues` Function App settings; no RBAC role assignment in Stage 1 |
| `amlRole.bicep` — `Create`-mode-only least-privilege RBAC (AzureML Data Scientist role for the queue Function App identity) | Local Bicep compilation and static inspection only | Kept ready but not applied during this rollout; never deployed in `Existing`/`Disabled` |
| Per-environment opt-in settings (`COMPUTE_BACKEND_*`, `AML_MODE`, `AML_*`) | `azd env set` → app settings | Per-environment |

## Feature Flags

| Flag | Location | Default | Description | Kill Switch? |
|---|---|---|---|---|
| `AML_MODE` | IaC parameter / app setting | `Disabled` | Controls whether AML resources exist at all | yes (`Disabled`) |
| `COMPUTE_BACKEND_DEFAULT` | app setting | `azure_batch` | Global fallback backend | yes (revert to `azure_batch`) |
| `COMPUTE_BACKEND_<WORKLOAD>` | app setting | unset | Per-workload override | yes (unset) |
| `COMPUTE_AUTO_CANDIDATES_<WORKLOAD>` | app setting | unset (no `auto` candidates until configured) | Backends `auto` may select | yes (unset disables `auto` for that workload) |
| `COMPUTE_FOLLOW_ON_INHERITS_BACKEND` | app setting | `true` | Automatic follow-on backend inheritance | yes (`false` reverts to workload default) |
| `RUNNER_TYPE` | app setting | — | Deprecated alias; still honored during migration | reverting it is equivalent to `COMPUTE_BACKEND_DEFAULT` |

Reverting all flags to their defaults restores exact current Batch-only
behavior with no data migration.

## Rollout Phases

### Phase 0: Prerequisites

- [x] Spec and ADR-0005 approved.
- [x] `security` review of the `azure-ai-ml==1.34.1` / `azure-identity`
      dependency set complete; `security-validation` confirmed.
- [ ] The operator-provided existing AML workspace, compute targets,
      immutable environments, datastore, and identity to reference under
      `AML_MODE=Existing` are identified before HASTE is configured — the
      deploying operator chooses their own tenant, subscription, region, and
      network placement for those resources; HASTE does not require a
      particular placement.
- [ ] Existing HASTE test suite green on `main` before starting the migration.

### Phase 1: Ship neutral contract, Batch/local adapters, compatibility fields (AML disabled)

- **Target:** all environments, normal deploy path.
- **Deployment:** merge the compute models, execution service, registry,
  router, migrated Batch/local adapters, and the additive `computeJob` field.
  `AML_MODE=Disabled` everywhere; `COMPUTE_BACKEND_DEFAULT=azure_batch`.
- **Success criteria:**
  - [ ] Existing environments behave identically to pre-migration Batch
        behavior — no regression.
  - [x] `rg "get_azure_batch_config|AZ_BATCH_" hastelib/src/hastegeo/core/processors`
        returns no matches.
  - [ ] Full `hastelib` test suite passes.
- **Rollback trigger:** any regression in existing Batch/local behavior →
  revert the branch.

### Phase 2: Reference existing AML resources (no AML resource deployment)

- **Target:** dedicated validation environment.
- **Deployment:** set `AML_MODE=Existing` and supply the existing workspace,
  resource group, compute target names, immutable environment references,
  datastore name, and identity mode (`AML_IDENTITY_MODE=user` by default —
  AML jobs submit as the calling Function App's own identity, needing no
  extra grant; `managed` requires `AML_MANAGED_IDENTITY_ID`). Do not create
  or mutate the workspace, compute, environments, datastore, or AML RBAC
  from HASTE.
- **Success criteria:**
  - [ ] Local Bicep compilation and static tests confirm `Existing` emits
        application settings but no `Microsoft.MachineLearningServices`
        resources.
  - [ ] CPU and GPU smoke jobs succeed (SMOKE-001/002 in
        [test-plan.md](test-plan.md)) without any application submission path
        enabled.
  - [ ] No account keys, passwords, or connection strings present anywhere in
        the deployed configuration.
- **Rollback trigger:** any smoke-job failure or credential-boundary finding
  → set `AML_MODE=Disabled`; there are no HASTE-created AML resources to
  remove.

> `Create` mode remains in source for a separately approved future deployment
> scenario. It is not applied under this rollout.

### Phase 3: Enable explicit AML for one short workload

- **Target:** validation environment, then one operator-designated
  non-production environment.
- **Deployment:** set `COMPUTE_BACKEND_IMAGERYPREP=azure_ml` (or artifact
  packaging — the shortest, CPU-only workload) for explicit per-job testing.
- **Success criteria:**
  - [ ] E2E-005 (or the imagery-prep equivalent) passes with output parity
        against the Batch baseline.
  - [ ] Cancellation and worker-restart resilience scenarios pass
        (E2E-007).
- **Rollback trigger:** output mismatch, cancellation failure, or handle
  routing error → unset the workload override, keep AML resources deployed
  for further investigation.

### Phase 4: Expand explicit AML to embedding, inference, training, remaining workload

- **Target:** the same operator-designated environment(s).
- **Deployment:** enable `COMPUTE_BACKEND_EMBEDDING`, `COMPUTE_BACKEND_INFERENCE`,
  `COMPUTE_BACKEND_TRAINING` in sequence, one at a time.
- **Success criteria (per workload, before moving to the next):**
  - [ ] Matching end-to-end test from [test-plan.md](test-plan.md) passes.
  - [ ] Duplicate-delivery and worker-restart scenarios pass for that
        workload.
- **Rollback trigger:** any workload-specific failure → unset that workload's
  override; already-validated workloads remain enabled.

### Phase 5: Enable mixed explicit Batch/AML submissions

- **Target:** the same operator-designated environment(s).
- **Deployment:** run a mix of jobs with explicit `azure_batch` and explicit
  `azure_ml` requests concurrently.
- **Success criteria:**
  - [ ] E2E-006 (mixed backend) passes — both backends complete correctly in
        one deployment.
  - [ ] Metrics show correct per-backend attribution (submissions,
        completions, failures, duration).
- **Rollback trigger:** cross-backend interference or incorrect handle
  routing → disable AML submissions, investigate before re-enabling.

### Phase 6: Enable `auto` with conservative weights

- **Target:** the same operator-designated environment(s), then broader
  rollout.
- **Deployment:** set `COMPUTE_AUTO_CANDIDATES_<WORKLOAD>` to include both
  backends for validated workloads, with `COMPUTE_AUTO_WEIGHTS_<WORKLOAD>`
  conservatively favoring Batch initially.
- **Success criteria:**
  - [ ] Routing, queue, quota, failure, and output-parity metrics are healthy
        over a deterministic sample of jobs.
  - [ ] `auto` never changes provider for the same `executionId` across
        retries.
- **Rollback trigger:** routing instability, quota contention, or output
  parity regression → unset `COMPUTE_AUTO_CANDIDATES_<WORKLOAD>` for the
  affected workload, falling back to explicit/default routing.

### Phase 7: Broader environment rollout

- **Target:** remaining environments, per environment owner decision.
- **Deployment:** repeat Phases 2–6 per environment; environments may choose
  to stay Batch-only indefinitely — this feature adds AML, it does not require
  adoption.
- **Success criteria:**
  - [ ] Each opted-in environment passes its own Phase 2–6 gates before
        `auto` is expanded further.

Batch remains enabled throughout every phase; this feature adds AML rather
than replacing Batch.

## Rollback Plan

| Step | Action | Owner |
|---|---|---|
| 1 | Unset `COMPUTE_BACKEND_<WORKLOAD>` / `COMPUTE_AUTO_CANDIDATES_<WORKLOAD>` on the affected environment | Platform Operator |
| 2 | Set `AML_MODE=Disabled` if AML infrastructure itself is implicated | Platform Operator |
| 3 | (If code-level) revert the merged branch / redeploy the previous release | backend-dev |
| 4 | Continue polling/cancelling/finalizing any already-submitted AML jobs by their persisted handle until terminal | backend-dev |
| 5 | Verify Batch-only jobs are unaffected and route correctly | backend-validation |
| 6 | Leave the operator-provided AML resources unchanged; HASTE rollback is configuration-only | Platform Operator |

Automatic cross-provider resubmission is never used as a rollback mechanism.
A job whose provider may have accepted it is reconciled or explicitly
retried as a new HASTE execution, never blindly resubmitted to a different
backend.

**Cosmos data rollback required?** no — `computeJob` is additive; legacy
`jobId`/`taskId` remain authoritative throughout.
**Blob artifacts cleanup needed?** no — output paths and containers are
unchanged by this feature.

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Baseline | Alert Threshold |
|---|---|---|---|
| Submissions/completions/failures/cancellations by backend and workload | Application telemetry | pre-rollout Batch-only rate | sustained increase in failure rate for either backend |
| Routing decisions and fallback counts | Application telemetry (`routingReason`) | n/a (new) | unexpected fallback rate for `auto` |
| Duplicate-submission reconciliation events | Application telemetry | 0 | any (should be rare and always resolved, never duplicated) |
| Provider API throttling | Application telemetry / provider SDK errors | 0 | sustained throttling on either backend |
| Queue wait and compute startup time by backend | Application telemetry | current Batch baseline | AML startup significantly exceeding Batch baseline |
| AML environment/image pull failures | Application telemetry / AML job diagnostics | 0 | any |
| Output synchronization or missing-output failures | Application telemetry | 0 | any |
| Credential/secret patterns in logs | Log scanning | 0 | any (security-critical) |

### Alerts to Configure

| Alert | Condition | Severity | Notify |
|---|---|---|---|
| Duplicate provider job detected | reconciliation logic reports a mismatch it cannot resolve | P0 | eng team |
| Cross-deployment access anomaly on AML compute | any unexpected storage access outside the granted datastore scope | P0 | eng team, security |
| AML submission failure rate | sustained increase vs. baseline | P1 | eng team |
| `auto` routing imbalance or repeated fallback | deviation from configured weights beyond tolerance | P2 | Platform Operator |
| AML compute allocation failure | pool/cluster can't scale up (quota) | P2 | Platform Operator |

## Communication Plan

| Audience | Channel | When | Message |
|---|---|---|---|
| Engineering team | GitHub PR / Teams | Pre-deploy of each phase | Rollout phase, flags, and rollback triggers |
| Platform Operators | Documentation channel / Teams | Before enabling AML per environment | AML is opt-in per workload; Batch remains the default |
| Disaster analysts / end users | — | Not required | No user-visible change; artifacts and statuses are identical across backends |

## Post-Rollout Checklist

- [ ] Flags and their defaults documented in `docs/configuration.md`
- [ ] `docs/architecture.md` / `spec/architecture/overview.md` updated to
      reflect the neutral runner and AML backend
- [ ] `CHANGELOG.md` updated
- [ ] GitHub Pages docs rebuilt (`docs-deploy.yml`)
- [ ] `README.md` status in this spec updated to `implemented`
- [ ] Deprecated `(job_id, task_id)` `BaseRunner` wrapper methods removed once
      all repository consumers have migrated (tracked in
      [plan.md](plan.md))
- [ ] `RUNNER_TYPE` deprecation alias removal scheduled once no environment
      still relies on it
