# HASTE Queue Functions

Azure Functions backend for asynchronous, queue-driven processing in HASTE.
Thin triggers delegate to `hastegeo.core.processors.job_queue`, which submits
and polls **local Docker, Azure Batch, or Azure Machine Learning** through
persisted compute handles. Queue messages are wake-ups: current metadata, not
the message snapshot, controls each revision-fenced processing turn.

Bindings are defined in `function_app.py`; business logic remains in `hastegeo`.

## Contents

- [Architecture](#architecture)
- [Azure Batch pools](#azure-batch-pools)
- [Queue triggers](#queue-triggers)
- [Recovery timers](#recovery-timers)
- [Error handling](#error-handling)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Development setup](#development-setup)

---

## Architecture

```
HTTP API → Azure Storage Queue → Azure Function (trigger)
                                        │
                                        ▼
                               Submit backend-neutral job
                                        │
                                        ▼
                            Local Docker / Batch / AML
                            executes the accepted job
                                        │
                               ┌────────┴────────┐
                               │  IN_PROGRESS?   │
                               │  Enqueue next   │← function exits after sending a new message
                               └────────┬────────┘  (delay via send_message visibility_timeout)
                                        │
                                   COMPLETED / FAILED
                                        │
                                  Save metadata,
                                  queue artifact zip
```

Each invocation submits or polls the current execution, commits only its
runtime fields, and queues another turn if needed. Accepted identities and
handles survive worker restarts. Cancellation and finalization use the
stored backend/profile, so changing defaults cannot redirect an existing job.

Local submission returns before input staging or container execution.
Durable receipts on the shared volume and deterministic Docker containers
own its lifecycle. The default host limit is one active job; queued work
waits for a slot, and successful exit is not success until outputs persist.

---

## Azure Batch Pools

There are two dedicated pools:

| Pool | Env Var | Default ID | Used By |
|------|---------|------------|---------|
| Imagery prep | `AZURE_BATCH_IMAGERYPREP_POOL_ID` | `imageryprep-pool` | `GetProcessImageLayerQueueMessage` |
| Training / Inference | `AZURE_BATCH_TRAINING_POOL_ID` | `training-pool` | `GetCreateModelRunQueueMessage`, `GetRunInferenceQueueMessage` |


Each pool runs tasks as Docker containers pulled from Azure Container Registry using managed identity. Containers run with `--shm-size=32g` for GPU workloads.

---

## Queue Triggers

### GetProcessImageLayerQueueMessage
**Queue:** `image_queue_name` | **Pool:** `imageryprep-pool`

Preprocesses a newly uploaded geospatial image layer. On each invocation:
- **PENDING** → submits a Batch task via `ImageryPostProcessor`; task runs `prepare-imagery` CLI inside the container
- **IN_PROGRESS** → reads `imagery_friendly.log` for progress, then re-queues
- **COMPLETED** → reads `imagery_manifest.json` for output paths (mosaics, COGs, building footprints, valid-area mask); generates label project files, converts to GeoJSON, stores artifacts
- **FAILED** → saves the layer with a FAILED status and error message

If the layer was deleted before processing starts, the message is silently skipped.

Both files are read from the compute node first and, if that node is no longer
able to serve them, from the copy Azure Batch uploaded to blob storage on task
completion (`outputs/` and `logs/` under `<projectHash>/<taskId>/`). On
autoscale pools the node is deallocated the moment the task completes — and
low-priority nodes can be preempted — so the node-local copy is frequently gone
by the time the trigger looks for it. The manifest is required (a layer with no
manifest in either place fails); the progress log is best-effort.

---

### GetCreateModelRunQueueMessage
**Queue:** `train_queue_name` | **Pool:** `training-pool`

Orchestrates ML model training. On each invocation:
- **PENDING** → submits a Batch training task; input files include labels (GeoJSON), pre/post-event COG imagery, optional initial weights, and experiment config (YAML)
- **IN_PROGRESS** → parses TensorBoard event files from the task working directory to extract per-epoch metrics (completed epochs, time per epoch, ETA), then re-queues
- **COMPLETED** → extracts final metrics; if `autoRunInference` is set, automatically enqueues an inference job
- **CANCELLED** → cancels the exact persisted compute handle
- **Post-run** → durably records artifact zipping for **FAILED/CANCELLED** training runs when `trainingOutputPath` exists (completed runs can be zipped on-demand via `PutArtifactsZipQueueMessage`)

---

### GetRunInferenceQueueMessage
**Queue:** `inference_queue_name` | **Pool:** `training-pool`

Runs model inference on a geospatial image layer. On each invocation:
- **PENDING** → submits a Batch inference task; inputs include COG imagery, building footprints GeoPackage, training checkpoint (`last.ckpt`), and experiment config
- **IN_PROGRESS** → reads `workflow_progress.log` from the task for user-visible progress messages, then re-queues
- **COMPLETED** → surfaces output artifact URLs: predicted damage layer (GeoTIFF) and vector predictions (GeoPackage)
- **CANCELLED** → cancels the exact persisted compute handle
- **Post-run** → durably records artifact zipping if an output path exists

> **Note:** Raw `stderr.txt` from the Batch task is never returned to the client — only sanitized `workflow_progress.log` messages are surfaced.

---

### UpdateStatsMessage
**Queue:** `stats_queue_name`

Lightweight function — no Batch involvement. Deserializes a `StatsRequest` message and runs `StatsPostProcessor` to recalculate and persist aggregated `ProjectsSummary` metadata.

---

### GetArtifactsZipQueueMessage
**Queue:** `zip_queue_name`

Packages training/inference output files into a downloadable zip archive via `ArtifactProcessor.process_zip()`. Triggered automatically by the training and inference functions after their runs complete (or fail with partial output).

---

### Poison queue handlers
**Queues:** imagery, training, embedding, inference, and artifact `-poison` queues

Handlers record interrupted delivery for the current attempt. A poison
message does not prove the compute failed and cannot overwrite a newer run.
Recovery is independent of `maxDequeueCount=1` in `host.json`.

## Recovery timers

`ReconcileLocalTasks` runs every 15 seconds while durable local receipts
exist. It resumes staging, inspects the owned Docker execution, persists
outputs, and releases admission slots without repeating completed compute.

`ReconcileJobQueues` runs every 30 seconds and wakes pending, running,
cancelling, or unfinished follow-on work after delivery or worker failure.
It is independent of local staging, so a long download does not block state
polling or cancellation. Cleanup is deferred until a fenced metadata commit;
failed persistence always retains local evidence.

---

## Error Handling

- **Poison queue:** Interrupted deliveries are recorded and recovered without assuming compute failed.
- **Follow-ons:** Inference and artifact requests are durable, idempotent actions; a failed queue send can be retried without repeating compute.
- **Status persistence:** Storage-native conditional writes fence attempts and claims. Transient polling/submission-recording errors remain recoverable rather than manufacturing success or a terminal compute failure.
- **Batch retry:** The `AzureBatchRunner` uses exponential backoff (4–10 s, up to 5 attempts) via `tenacity` for transient Azure Batch API errors (5xx).

---

## Configuration

Neutral backend/image/output settings are documented in the
[compute design](../../spec/features/aml-compute-backend/design.md).
`HASTE_LOCAL_MAX_ACTIVE_TASKS` defaults to `1` and accepts `1` through `64`;
all controllers sharing a Docker host must agree. See the
[local rollout requirements](../../spec/features/local-compute-lifecycle/design.md#configuration-and-rollout)
before changing this limit or rolling back.

### Azure Batch

| Environment Variable | Description | Default |
|----------------------|-------------|---------|
| `AZURE_BATCH_ACCOUNT_NAME` | Batch account name | — |
| `AZURE_BATCH_ACCOUNT_KEY` | Batch account key (if not using managed identity) | — |
| `AZURE_BATCH_ACCOUNT_URL` | Batch account endpoint URL | — |
| `AZURE_BATCH_TRAINING_POOL_ID` | Pool for training and inference; also the default training/inference job id | `training-pool` |
| `AZURE_BATCH_IMAGERYPREP_POOL_ID` | Pool for imagery preprocessing; also the default imageryprep/artifact job id | `imageryprep-pool` |
| `AZURE_BATCH_TRAINING_POOL_IDS` | Ordered candidate training pools (comma-separated) | `AZURE_BATCH_TRAINING_POOL_ID` |
| `AZURE_BATCH_INFERENCE_POOL_IDS` | Ordered candidate inference/embedding pools | training pool |
| `AZURE_BATCH_IMAGERYPREP_POOL_IDS` | Ordered candidate imageryprep/artifact pools | `AZURE_BATCH_IMAGERYPREP_POOL_ID` |
| `AZURE_BATCH_USE_SAS` | Per-job user-delegation SAS for blob I/O instead of the pool identity. Required for shared pools. | `false` |
| `AZURE_BATCH_MANAGE_POOLS` | Runner auto-creates/resizes its pool. Set `false` for pre-created autoscale pools. | `true` |
| `AZURE_BATCH_TARGET_DEDICATED_NODES` | Number of dedicated nodes per pool | `1` |
| `AZURE_BATCH_TARGET_LOW_PRIORITY_NODES` | Number of spot nodes per pool | `0` |
| `AZURE_BATCH_TASK_RETENTION_TIME` | ISO 8601 retention for task files | `P2D` |
| `TRAINING_BATCH_JOB_ID` | Job ID for training tasks | Pool ID |
| `INFERENCE_BATCH_JOB_ID` | Job ID for inference tasks | Pool ID |
| `IMAGERYPREP_BATCH_JOB_ID` | Job ID for imagery prep tasks | Pool ID |
| `ARTIFACT_BATCH_JOB_ID` | Job ID for artifact zip tasks | Pool ID |

### Container Registry

| Environment Variable | Description |
|----------------------|-------------|
| `AZURE_BATCH_REGISTRY_SERVER` | ACR login server (e.g. `myregistry.azurecr.io`). Falls back to the deprecated `AZURE_BATCH_REGISTRY_SERVER_URL`; a `https://` prefix is stripped. Only read when `AZURE_BATCH_MANAGE_POOLS` is true. |
| `AZURE_BATCH_DOCKER_IMAGE` | Training/inference Docker image (full tag) |
| `AZURE_BATCH_IMAGERYPREP_DOCKER_IMAGE` | Imagery preprocessing Docker image (full tag) |
| `AZURE_BATCH_REGISTRY_IDENTITY_RESOURCE_ID` | Managed identity resource ID for ACR pull |

### Queue & Storage

| Environment Variable | Description |
|----------------------|-------------|
| `AzureWebJobsStorage` | Azure Storage connection string (queues + blobs) |
| `DATA_DIR` | Root directory for app data and per-process log files |

---

## Deployment

The app ships as a Docker container.

**Base image:** `mcr.microsoft.com/azure-functions/python:4-python3.11`

The container runs as a non-root `appuser`. Its requirements default to an
editable `/home/hastelib` install so local Docker builds use the checked-out
source. Deployment CI rewrites that requirement to a validated release wheel.

```bash
docker build -t hastefuncqueues .
```

**host.json concurrency settings:**
- `batchSize=1` — process one queue message at a time per worker; local compute admission is separately host-wide
- `maxDequeueCount=1` — immediately dead-letter on failure
- Function timeout: `23:59:59` — the orchestration invocation limit, not the lifetime of a submitted compute job

---

## Development Setup

### Prerequisites

Install Azure Functions Core Tools:

```bash
npm install -g azure-functions-core-tools@4 --unsafe-perm true
```

### Running Locally

Set `AzureWebJobsStorage` and other required variables in `local.settings.json`, then:

```bash
func start
```

Or use the `Launch Functions` VS Code launch configuration.

### Local Debugging

Add a breakpoint in code:

```python
breakpoint()
```

Then use the `Launch Functions` VS Code task. The terminal drops into a `pdb` prompt when execution reaches the breakpoint.

> **Note:** The VS Code visual breakpoint UI will not work — the Azure Functions process is not attached to the VS Code Python debugger.
