# Design: Batch node-loss resilience

## Context

Azure Batch exposes two different classes of API:

| Class | Examples | Served by | Survives node loss |
|---|---|---|---|
| Job/task scope | `task.get`, `job.disable`, `task.add` | Batch service | yes |
| Node scope | `file.list_from_task`, `file.get_from_task`, `file.delete_from_task` | the compute node | **no** |

HASTE's post-task bookkeeping uses the second class. On a fixed, always-on pool
that is safe. On an autoscale pool with `$NodeDeallocationOption = taskcompletion`
— or on preemptible low-priority nodes — the node disappears the moment the task
finishes, which is precisely when the bookkeeping runs.

## Call path

```
GetProcessImageLayerQueueTrigger            api/hastefuncqueues/function_app.py
└── ImageryPostProcessor.process            hastelib/.../processors/imagery.py
    ├── runner.get_task_status              (job scope — safe)
    ├── _update_results_from_job
    │   └── _read_task_output("imagery_manifest.json")   ← node scope
    ├── _get_image_preprocess_logs
    │   └── _read_task_output("imagery_friendly.log")    ← node scope
    └── runner.cleanup_task
        └── delete_files_from_task                        ← node scope
```

## Contracts

### `hastegeo.core.runners.azure_batch`

```python
TRANSIENT_NODE_ERROR_CODES = frozenset({"NodeNotReady", "NodeStateInvalid"})
TERMINAL_NODE_ERROR_CODES = frozenset({"NodeNotFound"})

batch_error_code(exc) -> str | None      # None for non-Batch exceptions
is_transient_node_error(exc) -> bool
is_terminal_node_error(exc) -> bool
is_node_unavailable_error(exc) -> bool   # transient or terminal
is_retryable_batch_error(exc) -> bool    # 5xx or transient node error
unwrap_retry_error(exc) -> BaseException # the error tenacity was retrying
```

`retry_on_server_error()` keeps its name (it is applied to every `AzureBatchJob`
method by `apply_retry_to_methods`) but now retries on
`is_retryable_batch_error`. Its `reraise` setting is deliberately left at the
default — see the runner contract below.

| Aspect | Before | After |
|---|---|---|
| Retried | 5xx only | 5xx + transient node errors |
| Budget | 5 attempts, exponential 4–10s | unchanged |
| On exhaustion | `tenacity.RetryError` | unchanged — callers unwrap it with `unwrap_retry_error` |

### `AzureBatchRunner`

| Method | Contract |
|---|---|
| `get_filecontent_from_task` | returns file text, or `None` when the file is missing **or** the node cannot serve it. Unrelated `BatchErrorException`s propagate. |
| `cleanup_task` | best-effort working-directory delete: node-unavailability is swallowed and the job is then disabled. Any other error propagates **before** `disable_job` is reached, so callers must not treat the job as guaranteed disabled. |

An exhausted retry budget surfaces as `tenacity.RetryError`, not the underlying
error, so both methods classify through `unwrap_retry_error` before deciding.
`reraise=True` was deliberately **not** used: `apply_retry_to_methods` decorates
every `AzureBatchJob` method and several call one another
(`get_file_by_match_from_task` → `is_task_running` / `is_task_completed`), so
re-raising a retryable error from an exhausted inner budget would let the outer
wrapper spend a fresh one — 5 attempts silently becoming 25.

### `AzureBatchJob.add_task`

`file_pattern` accepts `str | list[str]`. Each pattern becomes its own
`OutputFile` against the same destination prefix; the `../*.txt` stdout/stderr
capture is appended as before. Existing string callers are unaffected.

| Workload | Patterns |
|---|---|
| imagery | `$AZ_BATCH_TASK_WORKING_DIR/outputs/*.*`, `$AZ_BATCH_TASK_WORKING_DIR/logs/*.*` |
| artifacts | `$AZ_BATCH_TASK_WORKING_DIR/outputs/*.*` |
| inference | `$AZ_BATCH_TASK_WORKING_DIR/inference/**/*` |
| train | `$AZ_BATCH_TASK_WORKING_DIR/**/*` |

`LocalRunner._upload_task_outputs` normalizes the same way, so a list pattern
cannot break it. Note this helper currently has **no call sites** —
`LocalRunner.add_task` accepts `file_pattern` but never consumes it, and the
docker dev stack uploads by walking the task directory. The normalization is
defensive only; it is not what keeps the local stack consistent today.

### `ImageryPostProcessor._read_task_output(filename) -> str | None`

```
node copy (runner.get_filecontent_from_task)
    └─ falsy? → storage.get_file_remote_path(
                    identifier=filename,
                    extra_partition_keys=<taskId>,
                    data_format=<ext>)
                → fetch_url_text(url)
    └─ any exception in the fallback → warn, return None
```

The blob path resolves to `<hash(projectId)>/<taskId>/<filename>` because
`UnifiedDataLayer` hashes the partition key with `MetadataUtils.hash_string` —
the same transformation `_execute_image_preprocess` uses to build
`output_prefix`. This is the path `_generate_imagery_url` already reads from in
production, so no new path convention is introduced.

| Caller | Missing file |
|---|---|
| `_update_results_from_job` | raises `FileNotFoundError` — the layer cannot complete without a manifest |
| `_get_image_preprocess_logs` | returns `[]` — progress detail only |

### `hastegeo.core.utils.blob.fetch_url_text(url, timeout=30) -> str | None`

Best-effort HTTP GET. Returns `None` for a falsy URL, a non-`http(s)` scheme
(a data layer resolving to a local filesystem path), or any transport/HTTP
error. It never raises: a failure here must not replace the original reason the
node read failed.

### `hastegeo.core.utils.errors.describe_exception(exc) -> str`

| Input | Output |
|---|---|
| `.error.code` + `.error.message.value` | `"<Code>: <message>"`, service `RequestId:`/`Time:` trailer stripped |
| `.error.code` only | `"<Code>"` |
| anything else | `str(exc)`, or the type name when empty |

Matched structurally, not by `isinstance`, so `hastegeo.core.utils` needs no
`azure.batch` import.

## Queue trigger

```python
output.statusMessage = MetadataUtils.append_status_message(
    output.statusMessage,
    f"Image layer processing failed: {describe_exception(e)}",
)
```

Appending preserves the progress history the status dialog renders. The
train/embedding/inference triggers already appended; they now use
`describe_exception` for the same readability.

No business logic was added to `function_app.py` — the formatter lives in
`hastegeo`, per the repository's function-app boundary rule.

## Rejected alternatives

| Alternative | Why not |
|---|---|
| Fix the pool (keep nodes alive after task completion) | Burns scarce GPU quota, and preemption of spot nodes remains possible regardless |
| Raise `maxDequeueCount` so the message is redelivered | Redelivery re-runs whole tasks; the fix belongs in-process |
| Add `extra_partition_keys` to `load()` across all five data layers | Wide blast radius for a fallback path; `load()` also returns `None` for non-json/yaml formats, so it cannot read the `.log` |
| A single `**/*` upload pattern for imagery | Would upload the raw downloaded imagery alongside the outputs |
| Poll node state before reading | Racy — the node can go away between the check and the read |
