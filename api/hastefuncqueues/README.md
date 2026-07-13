# HASTE Queue Functions

Azure Functions backend for asynchronous, queue-driven processing in HASTE. These functions act as **orchestrators** — they receive a queue message, submit a job to **Azure Batch** for the actual compute, and poll for completion across subsequent invocations by re-queuing themselves.

All functions are defined in `function_app.py`.

---

## Architecture

```
HTTP API → Azure Storage Queue → Azure Function (trigger)
                                        │
                                        ▼
                               Submit task to Azure Batch
                                        │
                                        ▼
                            Azure Batch Pool (GPU VMs)
                            runs Docker container task
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

Each function invocation either **starts** a new Batch task or **checks the status** of an existing one. When a task is still running, the function re-queues itself and exits — the Azure Functions runtime picks up the next message and checks again. This means a single training or inference job can span many function invocations over hours.

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
- **IN_PROGRESS** → reads `imagery_friendly.log` from the task working directory for progress, then re-queues
- **COMPLETED** → reads `imagery_manifest.json` for output paths (mosaics, COGs, building footprints, valid-area mask); generates label project files, converts to GeoJSON, stores artifacts
- **FAILED** → saves the layer with a FAILED status and error message

If the layer was deleted before processing starts, the message is silently skipped.

---

### GetCreateModelRunQueueMessage
**Queue:** `train_queue_name` | **Pool:** `training-pool`

Orchestrates ML model training. On each invocation:
- **PENDING** → submits a Batch training task; input files include labels (GeoJSON), pre/post-event COG imagery, optional initial weights, and experiment config (YAML)
- **IN_PROGRESS** → parses TensorBoard event files from the task working directory to extract per-epoch metrics (completed epochs, time per epoch, ETA), then re-queues
- **COMPLETED** → extracts final metrics; if `autoRunInference` is set, automatically enqueues an inference job
- **CANCELLED** → calls `TrainPostprocessor.cancel()` which terminates the Batch task
- **Post-run (separate error scope)** → queues artifact zipping for **FAILED/CANCELLED** training runs when `trainingOutputPath` exists (completed runs can be zipped on-demand via `PutArtifactsZipQueueMessage`)

---

### GetRunInferenceQueueMessage
**Queue:** `inference_queue_name` | **Pool:** `training-pool`

Runs model inference on a geospatial image layer. On each invocation:
- **PENDING** → submits a Batch inference task; inputs include COG imagery, building footprints GeoPackage, training checkpoint (`last.ckpt`), and experiment config
- **IN_PROGRESS** → reads `workflow_progress.log` from the task for user-visible progress messages, then re-queues
- **COMPLETED** → surfaces output artifact URLs: predicted damage layer (GeoTIFF) and vector predictions (GeoPackage)
- **CANCELLED** → calls `InferencePostprocessor.cancel()` which terminates the Batch task
- **Post-run (separate error scope)** → queues artifact zipping if output path exists

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

### ImagePoisonQueueHandler
**Queue:** `{image_queue_name}-poison` (dead-letter)

Handles image layer messages that exceeded the max dequeue count (`maxDequeueCount=1` in `host.json`). Marks the image layer as FAILED in metadata so the UI reflects the error. Training and inference failures are caught inline and do not have a poison handler.

---

## Error Handling

- **Poison queue:** Failed image processing messages are routed to the `-poison` dead-letter queue by the Azure Functions runtime after 1 failed attempt.
- **Tiered try/catch:** Training and inference use separate error scopes for each phase (main processing, artifact zipping, inference trigger) so a failure in one phase does not block the others.
- **Status persistence:** All failure paths attempt to write a FAILED or CANCELLED status back to metadata, even when the primary operation throws.
- **Batch retry:** The `AzureBatchRunner` uses exponential backoff (4–10 s, up to 5 attempts) via `tenacity` for transient Azure Batch API errors (5xx).

---

## Configuration

### Azure Batch

| Environment Variable | Description | Default |
|----------------------|-------------|---------|
| `AZURE_BATCH_ACCOUNT_NAME` | Batch account name | — |
| `AZURE_BATCH_ACCOUNT_KEY` | Batch account key (if not using managed identity) | — |
| `AZURE_BATCH_ACCOUNT_URL` | Batch account endpoint URL | — |
| `AZURE_BATCH_TRAINING_POOL_ID` | Pool for training and inference | `training-pool` |
| `AZURE_BATCH_IMAGERYPREP_POOL_ID` | Pool for imagery preprocessing | `imageryprep-pool` |
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
| `AZURE_BATCH_REGISTRY_SERVER` | ACR login server (e.g. `myregistry.azurecr.io`) |
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

The container runs as a non-root `appuser`. Local `hastegeo` source is copied in alongside the installed wheel to support development builds. Set `HASTE_SKIP_VERSION_BUMP=1` during the build to prevent version bumping.

```bash
docker build -t hastefuncqueues .
```

**host.json concurrency settings:**
- `batchSize=1` — process one queue message at a time per worker (one heavy job at a time)
- `maxDequeueCount=1` — immediately dead-letter on failure
- Function timeout: `23:59:59` — supports long-running training and inference jobs

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
