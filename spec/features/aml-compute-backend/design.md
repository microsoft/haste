# Design: Backend-neutral compute runner + Azure Machine Learning backend

## Overview

HASTE runs GPU/CPU workloads through `hastelib/src/hastegeo/core/runners/`.
Today `UnifiedRunner` is a two-entry factory over `AzureBatchRunner` and
`LocalRunner`, both of which implement a Batch-shaped `BaseRunner` contract
(`add_task(job_id, task_id, ...)`). This design introduces a backend-neutral
`ComputeRunner` contract, a `ComputeExecutionService` that owns idempotent
submission and handle-based lifecycle routing, a stateless `ComputeRouter` for
`auto` backend selection, and an Azure Machine Learning (AML) adapter that
implements the same contract as the Batch and local adapters. See
[user-stories.md](user-stories.md) for goals, [data-model.md](data-model.md)
for schema/config changes, [test-plan.md](test-plan.md) for verification, and
[rollout.md](rollout.md) for the phased rollout. Architecture rationale is
recorded in
[ADR-0005](../../architecture/decisions/0005-backend-neutral-compute-runner-and-aml-backend.md).

## Architecture

### Component diagram

```
 API launch / automatic follow-on / queue retry
                       |
                       v
          +---------------------------+
          | HASTE processor            |
          | (train/inference/embedding/ |
          |  imagery/artifacts)         |
          | builds ComputeJobSpec       |
          +-------------+-------------+
                        |
                        v
          +---------------------------+
          | ComputeExecutionService    |
          | - validate spec            |
          | - resolve backend          |
          | - idempotent submit        |
          | - route lifecycle ops by   |
          |   persisted handle         |
          +------+------+-------------+
                 |     |
       explicit  |     | auto
                 |     v
                 |  +----------------------+
                 |  | ComputeRouter        |
                 |  | health/capability +  |
                 |  | deterministic policy |
                 |  +----------+-----------+
                 |             |
                 v             v
       +----------------+  +----------------+
       | RunnerRegistry |  | Capacity cache |
       +---+--------+---+  +----------------+
           |        |
     +-----+--+  +--+-----------+  +----------------+
     | Batch  |  | Azure ML     |  | Local Docker   |
     | adapter|  | adapter      |  | adapter        |
     +---+----+  +------+-------+  +-------+--------+
         |              |                  |
         v              v                  v
   Batch pools     AML command jobs   Docker Engine
         |              |                  |
         +--------------+------------------+
                        |
                        v
             HASTE Blob/Data Lake paths
                        |
                        v
       persisted ComputeJobHandle on HASTE job record
       (TrainingJob / InferenceJob / ImageryPreprocessJob / ZipJob)
```

### New components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| Compute models | `hastelib/src/hastegeo/core/models/compute.py` | `ComputeJobSpec`, `ComputeJobHandle`, enums, capacity snapshot, typed exceptions | Pydantic |
| Compute execution service | `hastelib/src/hastegeo/core/runners/execution_service.py` | Validate spec, resolve backend, idempotent get-or-create submit, dispatch status/read/cancel/finalize by persisted handle | Python |
| Runner registry | `hastelib/src/hastegeo/core/runners/registry.py` | Construct/cache adapters by backend + profile; replaces the hard-coded two-entry import map | Python factory |
| Compute router | `hastelib/src/hastegeo/core/runners/router.py` | Resolve `auto` using capability filtering + deterministic weighted rendezvous hashing on `executionId` | Pure Python |
| AML adapter | `hastelib/src/hastegeo/core/runners/azure_ml.py` | Submit/poll/read/cancel/finalize AML command jobs behind `ComputeRunner` | `azure-ai-ml==1.34.1` (approved, pinned), `azure-identity` |
| Compute spec builders | next to each processor (e.g. `processors/train.py::build_training_job_spec()`) | Translate workload-specific inputs/outputs into a neutral `ComputeJobSpec` | Python |

### Modified components

| Component | Path | Change description |
|---|---|---|
| Runner base contract | `hastelib/src/hastegeo/core/runners/base.py` | Replaced with the `ComputeRunner` interface (`validate`, `submit`, `get_status`, `read_output`, `cancel`, `finalize`, `get_capacity`); deprecated `(job_id, task_id)` wrapper methods kept for one release |
| Batch adapter | `hastelib/src/hastegeo/core/runners/azure_batch.py` | Split low-level Batch API calls from `ComputeRunner` translation; preserves multi-pool routing/SAS from `batch-compute-expansion`; per-execution finalize no longer disables a shared Batch job with other active tasks |
| Local adapter | `hastelib/src/hastegeo/core/runners/local.py` | Implements `ComputeRunner` natively; Batch emulation (`AZ_BATCH_*` substitution) moves inside the adapter only |
| Unified factory | `hastelib/src/hastegeo/core/runners/unified_runner.py` | Replaced by `RunnerRegistry` + `ComputeExecutionService`; module kept temporarily as a deprecated re-export |
| Processors | `train.py`, `inference.py`, `embedding.py`, `imagery.py`, `artifacts.py` | Build `ComputeJobSpec`, call `ComputeExecutionService`, persist/read `ComputeJobHandle`; no direct `get_azure_batch_config()` |
| Job models | `hastelib/src/hastegeo/core/models/projects.py` | Add optional `computeJob: ComputeJobHandle` to `TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`, `ZipJob`; keep `jobId`/`taskId` |
| Config | `hastelib/src/hastegeo/core/config.py` | Add typed `ComputeConfig`/`AmlConfig` alongside `get_azure_batch_config()`; `RUNNER_TYPE` becomes a deprecated alias for `COMPUTE_BACKEND_DEFAULT` |
| Container scripts | `docker/training/scripts/set_dirs.sh`, `docker/imageryprep/scripts/set_dirs.sh`, `docker/training/code/run_workflow.py` | Read `HASTE_JOB_WORKDIR` first; fall back to `AZ_BATCH_TASK_WORKING_DIR` for already-released images |

## Backend-neutral contracts

Full field-level detail lives in [data-model.md](data-model.md). Summary:

### Enumerations

- `ComputeBackend`: `local`, `azure_batch`, `azure_ml`, `auto`
- `ComputeWorkload`: `training`, `inference`, `embedding`,
  `imagery_preparation`, `artifact_packaging`
- `ComputeJobState`: `pending`, `submitting`, `queued`, `preparing`, `running`,
  `succeeded`, `failed`, `cancelled`
- `InputKind`: `file`, `folder`
- `InputDeliveryMode`: `download`, `mount`, `direct`
- `OutputPersistenceMode`: `live_mount`, `upload_on_completion`
- `CapacityState`: `available`, `queueable`, `unavailable`, `unknown`

### `ComputeJobSpec`

Carries `executionId`, `workload`, `backendPreference`, a `container`
reference, an internal trusted `command`, typed `inputs`/`outputs`,
non-secret `environment`, `resources` (accelerator, node count, shared
memory, spot allowance, optional target override), `timeoutSeconds`, and
`tags`. Validation rejects absolute/`..` destination paths, output paths
outside the logical workspace, unrecognized URI schemes, unsupported
workload/backend combinations, and any credential or signed query string in
tags/logs. Image/environment immutability is enforced with two distinct
rules (see [data-model.md](data-model.md) for the exact validators):

- `container.imageReference` (the container image tag/digest, shared by
  every backend) rejects only the single mutable `:latest` tag in deployed
  environments — any other tag or an `@sha256:<digest>` reference is
  accepted, so existing Azure Batch deployments that pin a versioned,
  non-digest tag (e.g. `:v1.2.3`) keep working unchanged.
- `container.environmentReference` (the AML-specific, adapter-resolved
  environment *version* — unset for non-AML backends) enforces the
  stronger rule appropriate to AML environments: when set, it must
  reference a specific immutable version, not a `:latest`/`@latest` alias,
  in deployed environments.

### `ComputeJobHandle`

Persists `executionId`, `requestedBackend`, `selectedBackend`,
`backendProfile`, `providerJobId`, optional `providerTaskId`, `targetId`,
`outputUri`, `submittedAt`, `routingReason`, `attempt`, and a discriminated
`providerDetail` model (Batch job/task IDs, AML command-job name, or local
execution directory/process identity). It never persists tokens, account
keys, SAS tokens, or full signed input URLs.

### `ComputeRunner` interface

```python
validate(spec: ComputeJobSpec) -> None
submit(spec: ComputeJobSpec) -> ComputeJobHandle
get_status(handle: ComputeJobHandle) -> ComputeJobState
read_output(
    handle: ComputeJobHandle,
    relative_path: str,
    *,
    as_chunks: bool = False,
) -> str | Iterable[bytes] | None
cancel(handle: ComputeJobHandle) -> None
finalize(handle: ComputeJobHandle) -> None
get_capacity(
    workload: ComputeWorkload,
    resources: ComputeResources,
) -> CapacitySnapshot
```

Provider exceptions map to `BackendConfigurationError`,
`BackendUnavailableError`, `CapacityUnavailableError`,
`SubmissionIndeterminateError`, `JobNotFoundError`,
`OutputNotAvailableError`, and `JobCancellationError`, defined in
`hastegeo.core.models.compute`.

### Work-directory contract

`HASTE_JOB_WORKDIR` becomes the application-owned workspace variable used by
processor-generated YAML, commands, `set_dirs.sh`, and `run_workflow.py`. Each
adapter additionally exports legacy `AZ_BATCH_TASK_WORKING_DIR`,
`AZ_BATCH_JOB_ID`, and `AZ_BATCH_TASK_ID` so already-published container
images keep working during the transition. Command/bootstrap generation is
centralized in one tested module so quoting, input staging, and output-path
resolution are implemented once, not per adapter.

## Behavior & logic

### Backend resolution order

1. explicit per-job `backendPreference` on the `ComputeJobSpec`;
2. automatic follow-on inheritance from the originating job's selected
   backend, when `COMPUTE_FOLLOW_ON_INHERITS_BACKEND` is enabled and the next
   workload is supported there;
3. workload default (`COMPUTE_BACKEND_<WORKLOAD>`);
4. global default (`COMPUTE_BACKEND_DEFAULT`);
5. `auto` router policy.

### `auto` routing (`ComputeRouter`)

- Each adapter reports a `CapacitySnapshot` (`available`, `queueable`,
  `unavailable`, `unknown`) for a `(workload, resources)` pair.
- `auto` filters out backends that are incompatible with the workload or
  report `unavailable`, then ranks the remainder with deterministic weighted
  rendezvous hashing on `executionId` — the same job always hashes to the same
  backend given the same configured candidate set and weights, so retries do
  not need shared state.
- A configured provider priority (`COMPUTE_AUTO_WEIGHTS_<WORKLOAD>`) can
  override the default weighting for a workload.
- Fallback to the next candidate happens only for a classified
  configuration/availability/quota/capacity rejection raised *before* a
  provider may have accepted the deterministic job ID. Once a provider may
  have accepted a job, `ComputeExecutionService` reconciles against that
  provider only — it never submits the same `executionId` to a second
  backend.

### Idempotent submission (`ComputeExecutionService.submit`)

1. Generate/validate the deterministic `executionId` before any provider call.
2. Resolve the backend (explicit or `auto`) and persist
   `requestedBackend`/`selectedBackend`/`routingReason` on the pending job
   record before submission.
3. Call the adapter's `submit()`, which performs a get-or-create against the
   provider using a name/tag derived deterministically from `executionId`
   (Batch task ID, AML job name, local execution directory name).
4. If the provider call fails before acceptance is possible, retry against the
   next `auto` candidate (if any) or raise a classified error for explicit
   requests.
5. If the outcome is indeterminate (timeout, connection reset after the
   request may have reached the provider), reconcile via a provider `get`
   using the deterministic name instead of retrying `submit()` blindly.
6. Persist the returned `ComputeJobHandle` before the resource is
   re-queued for polling.

### Lifecycle dispatch

Every subsequent queue invocation loads the persisted `ComputeJobHandle` and
calls `ComputeExecutionService.get_status()` / `read_output()` / `cancel()` /
`finalize()`, which look up the adapter by `handle.selectedBackend` — never by
the current process-global default. This is what makes a
`COMPUTE_BACKEND_DEFAULT` change or worker restart safe mid-job.

### Data flow and lifecycle (end to end)

1. An API action or automatic follow-on creates a compute request with a
   requested backend (`azure_batch`, `azure_ml`, `local`, or `auto`).
2. Before queueing, HASTE generates the deterministic `executionId` and stores
   the backend preference with the pending resource.
3. The queue processor loads the resource and builds a `ComputeJobSpec` with a
   workload-specific builder; it does not read Batch settings directly.
4. `ComputeExecutionService` validates the spec and resolves the backend as
   described above.
5. The adapter performs an idempotent get-or-create submission using the
   deterministic provider job name and returns a `ComputeJobHandle`.
6. HASTE persists the handle, then re-queues the resource for polling.
7. On each queue invocation, `ComputeExecutionService` loads the persisted
   handle and dispatches status/output/cancel/finalize to the recorded
   backend.
8. The adapter normalizes provider states to `ComputeJobState`; processors map
   those to existing HASTE user statuses and progress messages.
9. Outputs remain under the existing `<project-hash>/<task-id>/...` HASTE
   storage prefix regardless of backend.
10. On success, processors update the same model/image-layer artifact URLs
    they use today.
11. On failure, the adapter surfaces a classified provider error; processors
    expose only sanitized, user-safe detail.
12. `finalize()` removes temporary execution resources. It does not delete AML
    run history and does not disable a Batch job that still owns active
    tasks.

### AML submission mapping

The AML adapter (`azure_ml.py`):

1. constructs `MLClient` with `DefaultAzureCredential` (lazy import/init — no
   AML SDK cost paid by Batch/local-only deployments);
2. resolves the configured workspace, compute target, datastore, and
   immutable environment version for the spec's container image reference;
3. maps neutral `inputs` to AML `Input` objects in `download` mode, matching
   Batch's current local-download behavior;
4. maps the HASTE output prefix to a named AML `uri_folder` output bound to
   the existing HASTE datastore (`rw_mount` where live progress files must
   stay observable, e.g. training TensorBoard events; `upload` only for
   workloads consumed after completion, e.g. artifact packaging);
5. generates a bootstrap command from the shared, fixed internal template
   that sets `HASTE_JOB_WORKDIR`, stages inputs into the requested
   destination-relative paths, and invokes the existing container command —
   never by concatenating untrusted input into the command string;
6. maps shared memory, instance count, timeout, priority, spot allowance,
   tags, and identity (`UserIdentityConfiguration` for `AML_IDENTITY_MODE=user`,
   `ManagedIdentityConfiguration(resource_id=AML_MANAGED_IDENTITY_ID)` for
   `managed`) into an AML command job;
7. submits with `ml_client.jobs.create_or_update` using a deterministic job
   name derived from `executionId`;
8. reconciles retries with `ml_client.jobs.get` by that deterministic name;
9. uses job status plus the named output/storage path for polling, output
   reads, and log reads;
10. uses AML job cancellation for `cancel()`;
11. retains the AML job record after HASTE `finalize()`.

### Workload migration matrix

| Workload | Current image | Inputs | Required output parity | Compute characteristics |
|---|---|---|---|---|
| Training | Training image | Config YAML, labels, raw/RGB COGs, optional initial checkpoint | Checkpoints, TensorBoard events, workflow progress, logs, all training artifacts | GPU; long-running; cancellation and live progress required |
| Inference | Training image | Config YAML, processed imagery, model checkpoint, building footprints | Inference COG/GeoPackage, progress log, stderr diagnostics | GPU; repeatable per model; output URL compatibility required |
| Embedding | Training image | Config, post-event mosaic, footprints | Embedding GeoJSON, PMTiles, feature sidecar, friendly log, manifest | GPU; large model/image downloads; manifest read required |
| Imagery preprocessing | Imagery-prep image | Config plus provider imagery URLs | COGs, previews, footprints, manifests, friendly logs | Storage/GDAL intensive; large file and CRS behavior unchanged |
| Artifact packaging | Imagery-prep image | Training and inference output folders | Training/inference ZIPs and manifest | Folder-input support; usually CPU; must not require a GPU target |

For each workload: extract a focused `build_*_job_spec()` function next to the
processor; preserve current image command and output naming; remove direct
`get_azure_batch_config()` use; add backend conformance fixtures that run the
same logical spec through fake Batch, AML, and local adapters; verify
automatic follow-on backend behavior explicitly. Automatic follow-ons use the
originating backend by default when the next workload is supported there; a
workload-specific configured override takes precedence, and the choice is
persisted with the queued request rather than inferred from current process
configuration.

## Configuration

See [data-model.md](data-model.md#configuration-changes) for the full
settings table. Highlights:

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| `COMPUTE_BACKEND_DEFAULT` | `ComputeBackend` | `azure_batch` | Function App settings | Global fallback backend |
| `COMPUTE_BACKEND_{TRAINING,INFERENCE,EMBEDDING,IMAGERYPREP,ARTIFACTS}` | `ComputeBackend` | unset (falls through to default) | Function App settings | Per-workload override |
| `COMPUTE_AUTO_CANDIDATES_<WORKLOAD>` | comma-separated `ComputeBackend` list | unset | Function App settings | Backends `auto` may select for a workload |
| `COMPUTE_AUTO_WEIGHTS_<WORKLOAD>` | comma-separated weights | unset (equal weight) | Function App settings | Overrides default rendezvous weighting |
| `COMPUTE_FOLLOW_ON_INHERITS_BACKEND` | bool | `true` | Function App settings | Automatic follow-ons reuse the originating backend when supported |
| `RUNNER_TYPE` | string | — | Function App settings | Deprecated alias for `COMPUTE_BACKEND_DEFAULT` during migration |
| `AML_MODE` | `Disabled` \| `Create` \| `Existing` | `Disabled` | IaC parameter / Function App setting | Controls whether HASTE provisions or references AML resources. Stage 1 rollout uses `Existing` as a pure reference to an operator-provided workspace/compute/environment/datastore/identity (no HASTE-created resources, no RBAC assignment). `Create` mode compiles locally and is available in source for a separately approved future scenario, but is not applied this rollout. `Disabled` (default) means HASTE creates no AML resource — it does **not** mean the `AML_*` application settings are omitted; see [Infrastructure](#infrastructure) below. |
| `AML_SUBSCRIPTION_ID`, `AML_RESOURCE_GROUP`, `AML_WORKSPACE_NAME`, `AML_DATASTORE_NAME`, `AML_COMPUTE_<WORKLOAD>`, `AML_ENVIRONMENT_<IMAGE>` | strings | unset | Function App settings | Required only when `AML_MODE != Disabled`; for `Existing` these identify the operator-provided resources to reference |
| `AML_IDENTITY_MODE` | `user` \| `managed` | `user` | Function App setting | Identity AML jobs submit/authenticate as. `user` (default) maps to AML's `UserIdentityConfiguration` — the job runs as the *submitting principal's own identity* (the calling Function App's identity), which needs no additional AML-specific grant beyond whatever access that identity already holds. `managed` maps to `ManagedIdentityConfiguration`, using a specific user-assigned managed identity instead. |
| `AML_MANAGED_IDENTITY_ID` | string | unset | Function App setting | User-assigned managed identity resource ID AML jobs submit as; required only when `AML_IDENTITY_MODE=managed`, ignored otherwise. |

Validation is conditional: AML settings are required only when AML is enabled
or explicitly selected for a job. A Batch-only deployment never imports
`azure-ai-ml` and pays no AML startup cost (lazy adapter import via
`RunnerRegistry`).

## Infrastructure

New Bicep modules under `infra/modules/`, covering three `amlMode` values
(`Disabled`/`Create`/`Existing`), mirroring the Batch `Create`/`Existing`
pattern from `batch-compute-expansion`. Bicep (`infra/main.bicep` plus these
modules) is the canonical, AML-capable deployment path — it is the only path
that wires the full `AML_*` application-setting set and the Create-mode
resource/RBAC modules. Legacy setup scripts (`.github/scripts/deploy_apps.sh`
and `setup/deploy_apps.sh`) are gaining partial AML awareness (e.g. a
`COMPUTE_BACKEND_DEFAULT` setting) incrementally, but do not yet wire the
full `AML_*` setting set; neither path performs a live deployment as part of
this rollout.

- `amlWorkspace.bicep` — `Create` provisions a keyless
  (system/user-assigned identity only) AML workspace with diagnostic
  settings; `Existing` emits no resource and only wires application settings
  that reference an operator-provided workspace.
- `amlCompute.bicep` — `Create` provisions scale-to-zero GPU/CPU compute
  clusters with bounded `maxInstanceCount`, one cluster per workload tier;
  `Existing` references operator-provided compute target names only.
- `amlEnvironment.bicep` — `Create` registers immutable AML environment
  versions pointing at the same container image tag/digest Batch uses,
  creating a new version only when the bound image reference changes;
  `Existing` references operator-provided environment versions only.
- `amlDatastore.bicep` — `Create` registers the HASTE storage account as an
  AML datastore via identity-based access (no account key); `Existing`
  references an operator-provided datastore name only.
- `amlRole.bicep` — `Create`-mode-only least-privilege AML RBAC: grants the
  built-in *AzureML Data Scientist* role (submit/read/cancel jobs, read
  compute — explicitly excluding workspace management and compute
  create/delete/listKeys) to the queue Function App's identity, scoped to
  the just-created workspace's resource group. ACR pull for the registered
  environment image reuses the existing shared ACR-pull grant Batch already
  has (`acrRole.bicep`); no separate AML-specific ACR grant is added.

**Stage 1 rollout uses `Existing` as a pure reference.** In `Existing` mode
HASTE creates no AML resource and assigns no RBAC role — `amlRole.bicep` is
never deployed in this mode. Granting the identity HASTE runs as sufficient
access to the operator-provided workspace, compute, environment(s), and
datastore is the deploying operator's responsibility, performed outside
HASTE's IaC. `Create` mode (which would additionally deploy `amlRole.bicep`)
compiles locally and is retained in source for a separately approved future
scenario, but is not applied during this rollout.

**`Disabled` (default) means HASTE creates no AML resource — it does not
mean the `AML_*` application settings are absent.** The Function App
settings module (`functions.bicep`) unconditionally emits every `AML_*`
key (`AML_MODE`, `AML_SUBSCRIPTION_ID`, `AML_WORKSPACE_NAME`,
`AML_IDENTITY_MODE`, and the rest) on every deployment, regardless of
`amlMode`; when `Disabled` those values are simply inert (for example,
`AML_MODE=Disabled`, resource identifiers empty, and
`AML_IDENTITY_MODE=user`) rather than the keys being omitted from the
settings collection. AML settings are only required and validated when
`AML_MODE != Disabled` or a job explicitly requests `azure_ml`.

All three modes are verified with local Bicep compilation and static
template checks; this rollout performs no Azure deployment operation
(`az deployment ... what-if` or apply) for the AML modules (see
[test-plan.md](test-plan.md)).

## Security

- Use `DefaultAzureCredential` for AML; never add AML keys, passwords, or
  other standing secrets.
- The job-submission identity defaults to `AML_IDENTITY_MODE=user`: AML jobs
  run as the *submitting principal's own identity* (the calling Function
  App's identity), which needs no additional AML-specific grant beyond
  whatever access it already holds. `AML_IDENTITY_MODE=managed` submits as a
  specific user-assigned managed identity (`AML_MANAGED_IDENTITY_ID`)
  instead. In `Existing` mode, granting either identity access on the
  operator-provided AML platform (workspace RBAC, datastore/storage access,
  ACR pull) is that platform's responsibility — HASTE's IaC only emits the
  identity-mode setting, it grants no AML permission. In `Create` mode (not
  applied this rollout), the equivalent HASTE-managed grant is
  `amlRole.bicep` (queue Function App identity only).
- Shared AML compute must not gain standing access to storage outside its own
  deployment — preserve the `batch-compute-expansion` credential-boundary
  isolation principle; add cross-deployment negative tests if multiple HASTE
  deployments ever share one AML workspace/cluster.
- Remove raw `resource_files_for_upload`-style logging; sanitize all URIs
  before logging across every adapter.
- Never place signed URLs, tokens, user data, or full storage paths in AML
  tags or `ComputeJobHandle` fields.
- Validate all relative paths and URI schemes before generating shell
  commands; use the fixed internal bootstrap template — never concatenate
  untrusted input into a command string.
- The `azure-ai-ml` dependency (pinned `azure-ai-ml==1.34.1`) and its
  transitive packages were evaluated and approved by the `security` agent;
  `security-validation` confirmed the resolved lockfile.

## Observability

Every log line and provider tag includes: HASTE `executionId`; workload;
selected backend; backend profile and target; project/model/image-layer
identifiers where non-sensitive; provider job ID; routing reason; submission
attempt; normalized status and raw provider status. Metrics: submissions,
completions, failures, cancellations, and duration by backend and workload;
routing decisions and fallback counts; duplicate-submission reconciliation
events; provider API throttling; queue-wait and compute-startup time; AML
environment/image pull failures; Batch and AML capacity state; output
synchronization or missing-output failures.

## Edge cases and failure behavior

- **Legacy job without a neutral handle:** synthesize a Batch handle and
  continue polling; never reinterpret it using the current default backend.
- **Configuration changes while a job runs:** use the persisted backend
  profile and provider ID; reject removal of a profile with active jobs.
- **Worker fails after provider acceptance:** look up the deterministic
  provider job name and reconcile the existing run instead of submitting
  another.
- **Two workers race to submit one execution:** one create succeeds; the
  other retrieves and validates the existing job on conflict.
- **Explicit backend disabled or incompatible:** fail before any provider call
  with an actionable configuration error; never silently select another
  backend.
- **`auto` backend unavailable:** remove only candidates with a classified
  pre-acceptance failure, then evaluate the next deterministic candidate.
- **Submission outcome indeterminate:** reconcile against the same provider;
  never cross-submit and risk a duplicate GPU job.
- **AML compute scales from zero:** report `queued`/`preparing`, not failure.
- **AML environment/ACR access missing:** fail with a sanitized
  environment-resolution error naming the configured environment, not
  credentials.
- **Folder input:** preserve the expected destination-relative directory
  shape for artifact packaging and checkpoint inputs.
- **Large COG input:** let the provider download/mount directly into the
  logical workspace; avoid an extra Function-host copy.
- **Live progress file not yet present:** return `None` (not-yet-available),
  distinct from provider failure.
- **Output exists after compute node loss:** read from durable HASTE storage
  or the AML named output, not the original node.
- **Cancellation races with completion:** refresh provider state; completed
  stays completed, otherwise normalize to `cancelled`.
- **Finalization is repeated:** make it idempotent.
- **Batch job has other active tasks:** finalizing one logical execution never
  disables the whole shared Batch job.
- **Unknown provider status:** raise an explicit mapping error and log the raw
  provider state server-side; never silently report `in-progress`.
- **Provider throttling/transient errors:** bounded retries with jitter only
  on documented idempotent reads or deterministic submissions.
- **Output path collision:** include deterministic execution/task identity and
  reject reuse with incompatible job metadata.
- **Automatic follow-on lacks support on the originating backend:** apply the
  configured workload policy and record the reason a different backend was
  selected.

## Scaling and bottlenecks

- Batch keeps its existing candidate-pool/autoscale strategy inside its
  adapter.
- AML compute clusters use `min_instances=0`, bounded `max_instances`, and
  workload-appropriate GPU/CPU SKUs.
- `auto` spreads jobs statelessly across healthy providers with deterministic
  weights; no central lock or broker.
- Provider clients are created lazily and cached per process by immutable
  backend profile.
- Capacity snapshots are short-lived and advisory; provider-native schedulers
  remain authoritative.
- First bottlenecks: GPU quota/cold-start capacity, container/environment
  preparation latency, storage throughput for large COGs/checkpoints, queue
  polling volume on many long-running jobs, and control-plane throttling
  differences between Batch and AML. Mitigations are per-provider bounded
  targets, immutable environment/image-digest caching, direct provider
  transfer (never through the Function App), status-aware polling intervals,
  and per-provider throttle classification/metrics.

## Open Questions

- [ ] Which existing tenant, subscription, region, and network placement the
      deploying operator points `Existing` mode at is a per-deployment
      operator decision, not something this design fixes; this design does
      not assume a shared workspace across deployments is reachable or
      authorized.
- [ ] Whether `auto` should ever prefer AML over Batch by default, or start
      Batch-weighted until AML capacity/cost data accumulates.
