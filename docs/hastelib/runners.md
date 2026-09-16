# Runners: backend-neutral compute

The `hastegeo.core.runners` package (plus `hastegeo.core.models.compute`)
submits and tracks HASTE's compute-intensive workloads — training,
inference, embedding, imagery preprocessing, and artifact packaging — on
whichever backend a deployment has configured: **Azure Batch**, **Azure
Machine Learning (AML)**, or **local Docker**. Architecture rationale lives
in [ADR-0005](https://github.com/microsoft/haste/blob/main/spec/architecture/decisions/0005-backend-neutral-compute-runner-and-aml-backend.md);
full behavioral detail is in
[`spec/features/aml-compute-backend/design.md`](https://github.com/microsoft/haste/blob/main/spec/features/aml-compute-backend/design.md).
For configuration settings, see [Configuration Guide § Compute backend selection](../configuration.md#compute-backend-selection-batch-azure-machine-learning-local)
and [§ Azure Machine Learning backend](../configuration.md#azure-machine-learning-backend).

## Contents

- [Backend-neutral contract](#backend-neutral-contract)
- [Compute models](#compute-models-hastegeocoremodelscompute)
- [Execution service, registry, and router](#execution-service-registry-and-router)
- [Backend adapters](#backend-adapters)
- [Workloads](#workloads)
- [Per-job backend selection and auto routing](#per-job-backend-selection-and-auto-routing)
- [Persisted handles and legacy jobs](#persisted-handles-and-legacy-jobs)
- [Work-directory contract (`HASTE_JOB_WORKDIR`)](#work-directory-contract-haste_job_workdir)
- [Deprecated: `UnifiedRunner` / `BaseRunner`](#deprecated-unifiedrunner--baserunner)

## Backend-neutral contract

Every backend implements `ComputeRunner`
(`hastegeo.core.runners.base.ComputeRunner`) over two neutral models instead
of Azure Batch's `(job_id, task_id)` shape:

- **`ComputeJobSpec`** — what to run: workload, backend preference,
  container/image reference, an internal trusted command, typed
  inputs/outputs, non-secret environment, resource request, timeout, and
  tags.
- **`ComputeJobHandle`** — what ran, and where to find it again: requested
  and selected backend, backend profile, provider job/task identifiers, the
  output URI, and why that backend was chosen. This is what gets persisted
  on the HASTE job record.

Also in `base.py`: the legacy `BaseRunner` contract (see
[Deprecated](#deprecated-unifiedrunner--baserunner)) and the shared
spec-translation helpers the Batch and local adapters both use to translate
`ComputeJobSpec` into their existing input/output handling.

```{eval-rst}
.. automodule:: hastegeo.core.runners.base
   :members:
   :undoc-members:
   :show-inheritance:
```

Callers should never invoke an adapter directly — always go through
`ComputeExecutionService` so lifecycle calls are dispatched by the
persisted handle, not by whatever backend happens to be configured as the
default right now.

## Compute models (`hastegeo.core.models.compute`)

`ComputeJobSpec`, `ComputeJobHandle`, the shared enumerations
(`ComputeBackend`, `ComputeWorkload`, `ComputeJobState`, `InputKind`,
`InputDeliveryMode`, `OutputPersistenceMode`, `CapacityState`), the
capacity/error models, and the path/URI/credential validation helpers every
adapter reuses.

```{eval-rst}
.. automodule:: hastegeo.core.models.compute
   :members:
   :undoc-members:
   :show-inheritance:
```

## Execution service, registry, and router

### `ComputeExecutionService` (`hastegeo.core.runners.execution_service`)

Owns idempotent submission and handle-based lifecycle dispatch:

- **`submit()`** resolves `spec.backendPreference` (explicit backend, or
  `auto`), validates the spec against the resolved adapter, and performs a
  get-or-create submission keyed by the spec's deterministic
  `executionId` — safe to call again after a worker restart or a retried
  indeterminate outcome without creating a second provider job.
- **`get_status()` / `read_output()` / `cancel()` / `finalize()`** all
  resolve the adapter from the persisted `ComputeJobHandle.selectedBackend`
  and `backendProfile` — never from the current process-global default —
  so a `COMPUTE_BACKEND_DEFAULT` change or a worker restart mid-job stays
  correct.

```{eval-rst}
.. automodule:: hastegeo.core.runners.execution_service
   :members:
   :undoc-members:
   :show-inheritance:
```

### `RunnerRegistry` (`hastegeo.core.runners.registry`)

Constructs and caches `ComputeRunner` adapters by `(backend, profile)`. No
adapter module is imported until first requested for a given key, so a
Batch/local-only deployment never imports or initializes the optional AML
SDK. Replaces `UnifiedRunner`'s hard-coded two-entry import map.

```{eval-rst}
.. automodule:: hastegeo.core.runners.registry
   :members:
   :undoc-members:
   :show-inheritance:
```

### `ComputeRouter` (`hastegeo.core.runners.router`)

Stateless resolver for `ComputeBackend.AUTO`: filters candidates by
adapter-reported `CapacitySnapshot`, then ranks the remainder with
deterministic weighted rendezvous hashing on `executionId`, so the same job
always resolves to the same backend given the same configured candidates
and weights — no shared routing state needed across retries. See
[Per-job backend selection and auto routing](#per-job-backend-selection-and-auto-routing).

```{eval-rst}
.. automodule:: hastegeo.core.runners.router
   :members:
   :undoc-members:
   :show-inheritance:
```

## Backend adapters

| Backend | Class | Module | Notes |
|---|---|---|---|
| Azure Batch | `AzureBatchRunner` | `hastegeo.core.runners.azure_batch` | GPU-enabled task execution on Azure Batch pools; multi-pool candidate routing and SAS behavior unchanged from before this migration |
| Azure Machine Learning | `AzureMLRunner` | `hastegeo.core.runners.azure_ml` | Submits AML command jobs via `azure-ai-ml` (SDK v2), lazily imported so a Batch/local-only deployment never pays its import cost |
| Local Docker | `LocalRunner` | `hastegeo.core.runners.local` | Runs the same container images locally via the Docker Engine; backs the Docker Compose dev stack |

### Azure Batch (`hastegeo.core.runners.azure_batch`)

```{eval-rst}
.. automodule:: hastegeo.core.runners.azure_batch
   :members:
   :undoc-members:
   :show-inheritance:
```

### Azure Machine Learning (`hastegeo.core.runners.azure_ml`)

Maps a `ComputeJobSpec` to an AML command job: resolves the configured
workspace/compute/datastore/environment, maps neutral inputs to AML
`Input` objects, binds `HASTE_JOB_WORKDIR` to a named `uri_folder` output on
the configured HASTE datastore, submits with `ml_client.jobs.create_or_update`
using a name derived deterministically from `executionId`, and reconciles
retries with `ml_client.jobs.get` by that same name. Uses
`DefaultAzureCredential` — no AML account keys or other standing secrets.
This adapter never creates, updates, or deletes an AML workspace, compute
cluster, environment, or datastore; it only ever consumes resources that
already exist. See
[Azure Machine Learning backend](../configuration.md#azure-machine-learning-backend)
for the `AML_*` settings that name those resources.

```{eval-rst}
.. automodule:: hastegeo.core.runners.azure_ml
   :members:
   :undoc-members:
   :show-inheritance:
```

### Local Docker (`hastegeo.core.runners.local`)

```{eval-rst}
.. automodule:: hastegeo.core.runners.local
   :members:
   :undoc-members:
   :show-inheritance:
```

## Workloads

All five HASTE compute workloads run through the same neutral contract. A
`build_*_job_spec()` helper next to each processor translates
workload-specific inputs/outputs into a `ComputeJobSpec`; nothing in a
processor reads Azure Batch settings or an `AZ_BATCH_*` variable directly
anymore.

| Workload | `ComputeWorkload` value | Builder | Compute characteristics |
|---|---|---|---|
| Training | `training` | `hastegeo.core.processors.train.build_training_job_spec` | GPU; long-running; cancellation and live progress required |
| Inference | `inference` | `hastegeo.core.processors.inference.build_inference_job_spec` | GPU; repeatable per model |
| Embedding | `embedding` | `hastegeo.core.processors.embedding.build_embedding_job_spec` | GPU; large model/image downloads |
| Imagery preprocessing | `imagery_preparation` | `hastegeo.core.processors.imagery.build_imagery_job_spec` | Storage/GDAL intensive; CPU-only |
| Artifact packaging | `artifact_packaging` | `hastegeo.core.processors.artifacts.build_artifact_zip_job_spec` | Folder-input support; CPU-only, must never require a GPU target |

Outputs land under the same `<project-hash>/<task-id>/...` HASTE storage
prefix regardless of backend, so existing result URLs keep resolving.

## Per-job backend selection and auto routing

Each launch-capable record (`Model`, `ImageLayer`, `ModelArtifacts`) accepts
an optional, client-supplied `computeBackend`
(`hastegeo.core.models.compute.ComputeBackend`: `local`, `azure_batch`,
`azure_ml`, or `auto`). Backend resolution order for a submission:

1. the preference on the request/record, or inherited from the originating
   job of an automatic follow-on when `COMPUTE_FOLLOW_ON_INHERITS_BACKEND`
   is enabled and the next workload supports that backend;
2. the configured per-workload override (`COMPUTE_BACKEND_<WORKLOAD>`);
3. the configured global default (`COMPUTE_BACKEND_DEFAULT`, or its
   deprecated `RUNNER_TYPE` alias).

`auto` defers to `ComputeRouter`: each candidate backend reports a
`CapacitySnapshot` (`available` / `queueable` / `unavailable` / `unknown`)
for the requested `(workload, resources)`; unavailable candidates are
dropped and the remainder are ranked by deterministic weighted rendezvous
hashing on `executionId`, so the same job always resolves to the same
backend across retries. A pre-acceptance rejection (configuration or
capacity) falls through to the next candidate; once a provider may have
accepted the job, `ComputeExecutionService` reconciles against that
provider only — it never submits the same `executionId` to a second
backend. See
[Compute backend selection](../configuration.md#compute-backend-selection-batch-azure-machine-learning-local)
for the `COMPUTE_AUTO_CANDIDATES_<WORKLOAD>` / `COMPUTE_AUTO_WEIGHTS_<WORKLOAD>`
settings that configure `auto` per workload.

## Persisted handles and legacy jobs

`TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`, and `ZipJob` each
carry an optional, server-owned `computeJob: ComputeJobHandle` alongside the
legacy `jobId`/`taskId` strings. New submissions populate both during the
compatibility window. A request body can never set `computeJob` directly —
it is cleared at the request-handling boundary
(`hastegeo.core.utils.compute_jobs.clear_compute_handles`) so a caller can
never redirect HASTE's polling/cancellation to an arbitrary provider job.

For a legacy record that has `jobId`/`taskId` but no `computeJob` (submitted
before this compute layer existed),
`hastegeo.core.utils.compute_jobs.resolve_compute_job_handle` synthesizes a
Batch `ComputeJobHandle` at read time (`selectedBackend=azure_batch`,
`routingReason="legacy-synthesized"`). No Cosmos backfill/migration is
required — this is a compatible additive field.

```{eval-rst}
.. automodule:: hastegeo.core.utils.compute_jobs
   :members:
   :undoc-members:
   :show-inheritance:
```

## Work-directory contract (`HASTE_JOB_WORKDIR`)

`HASTE_JOB_WORKDIR` is the application-owned workspace variable used by
processor-generated commands, `set_dirs.sh`, and `run_workflow.py` inside
the training/imagery-prep container images. Each adapter exports it:

- **Azure Batch** exports it from `AZ_BATCH_TASK_WORKING_DIR`.
- **Local Docker** sets it directly on the container.
- **Azure Machine Learning** binds it to the job's durable named output.

Every adapter additionally exports the legacy `AZ_BATCH_TASK_WORKING_DIR`,
`AZ_BATCH_JOB_ID`, and `AZ_BATCH_TASK_ID` variables so already-published
container images keep working unchanged during the transition;
`set_dirs.sh` reads `HASTE_JOB_WORKDIR` first and only falls back to the
legacy Batch variable.

```{eval-rst}
.. automodule:: hastegeo.core.utils.compute_specs
   :members:
   :undoc-members:
   :show-inheritance:
```

## Deprecated: `UnifiedRunner` / `BaseRunner`

`UnifiedRunner` (the two-entry `azure_batch`/`local` factory) and the
Batch-shaped `BaseRunner` contract (`add_task`, `get_filecontent_from_task`,
`get_task_status`, `cleanup_task`, `cancel_task`) predate the backend-neutral
compute layer and are kept only for backward compatibility. New code should
use `ComputeExecutionService` with an adapter that implements `ComputeRunner`
instead.

```{eval-rst}
.. automodule:: hastegeo.core.runners.unified_runner
   :members:
   :undoc-members:
   :show-inheritance:
```
