# Batch node-loss resilience

**Status:** implemented
**Type:** modification (fix)
**Related:** [`../batch-compute-expansion/`](../batch-compute-expansion/)
(shared autoscale/spot pools), [`../batch-pool-job-binding/`](../batch-pool-job-binding/)
(job/pool binding)

## Problem

Processing new imagery on **dev1** failed, and the UI status dialog showed a raw
Azure SDK dump as the entire status history for the layer:

```
Request encountered an exception.
Code: NodeNotReady
Message: {'additional_properties': {}, 'lang': 'en-US', 'value': 'Node is not
able to perform the requested operations in its current state
RequestId:a61bf14a-dcf1-4a68-b0ab-dddb878b4951
Time:2026-08-12T20:19:59.1266709Z'}
```

The Batch task itself ran fine. The imagery it produced was already in blob
storage. The layer was still marked FAILED.

## Root cause

`ImageryPostProcessor.process` reacts to a task reaching a terminal state by
reading files **back off the compute node**:

| Call | Batch API | Purpose |
|---|---|---|
| `_get_image_preprocess_logs` | `file.list/get_from_task` | `imagery_friendly.log` |
| `_update_results_from_job` | `file.list/get_from_task` | `imagery_manifest.json` |
| `runner.cleanup_task` | `file.delete_from_task` | working-directory cleanup |

Those APIs are served **by the node**, and the node is being torn down at exactly
that moment:

1. `infra/modules/batchPool.bicep` sets `$NodeDeallocationOption = taskcompletion`.
2. The shared-dev pools dev1 targets are autoscale with `minNodes = 0` and
   low-priority (spot) nodes, so they can also be preempted
   (see [`../batch-compute-expansion/design.md`](../batch-compute-expansion/design.md)).

A deallocating, rebooting or preempted node answers `NodeNotReady`.

Three properties then turned a transient race into a permanent failure:

| Property | Effect |
|---|---|
| `NodeNotReady` is HTTP **409**, and `is_server_error` only retried 5xx | never retried |
| The imagery queue trigger did `statusMessage = str(e)` | wiped the entire progress history with the SDK repr |
| `host.json` sets `maxDequeueCount: 1` | the message is never redelivered |

**The outputs were never lost.** Batch uploads `outputs/*.*` to blob on task
completion (`OutputFileUploadCondition.task_completion`), so the manifest was
sitting at `<projectHash>/<taskId>/imagery_manifest.json` — the same path
`_generate_imagery_url` already resolves. The processor simply never looked
there. `imagery_friendly.log` is written to `logs/`, which no upload pattern
covered, so it only ever existed on the node.

## Design

Three layers, all in code — the pool configuration is unchanged.

### 1. Classify node errors, and retry the transient ones

`hastegeo.core.runners.azure_batch` gains:

| Set | Codes | Treatment |
|---|---|---|
| `TRANSIENT_NODE_ERROR_CODES` | `NodeNotReady`, `NodeStateInvalid` | retried — a starting/rebooting node recovers |
| `TERMINAL_NODE_ERROR_CODES` | `NodeNotFound` | not retried — a deallocated node never comes back |

`is_retryable_batch_error` = 5xx **or** transient node code, and is now the
predicate behind `retry_on_server_error()`. The retry budget is unchanged
(5 attempts, exponential 4–10s), and `reraise` is deliberately left at its
default: `apply_retry_to_methods` decorates every `AzureBatchJob` method and
several call one another, so re-raising a retryable error from an exhausted
inner budget would let the outer wrapper spend a fresh one (5 attempts becoming
25). Callers recover the underlying error with `unwrap_retry_error` instead.

### 2. Degrade instead of failing

| Method | Behavior on node loss |
|---|---|
| `AzureBatchRunner.get_filecontent_from_task` | logs a warning, returns `None` — matching its existing "file not found" contract |
| `AzureBatchRunner.cleanup_task` | skips the working-directory delete, then disables the job (`task_retention_time=P2D` reclaims the disk) |

This applies to every workload on the runner: imagery, train, inference,
artifacts and embedding.

It does **not** mean every workload now survives node loss. `train`, `inference`
and `artifacts` treat a missing task file as absent progress/logs and continue,
so they do. `EmbeddingPostprocessor._update_results_from_job` raises
`FileNotFoundError` on a falsy `embedding_manifest.json`, so an embedding job
whose node vanished still fails — with a clearer error than before, but it
fails. That is a known gap, not a regression: previously the same case failed
with the raw `BatchErrorException`. Closing it means giving embedding the same
blob fallback as imagery (step 3), which is deliberately out of scope here.

### 3. Recover the outputs from blob (imagery)

`ImageryPostProcessor._read_task_output(filename)` reads the node copy first,
then falls back to the uploaded copy via
`storage.get_file_remote_path(identifier=filename, extra_partition_keys=taskId)`
and `hastegeo.core.utils.blob.fetch_url_text`. A failing fallback returns `None`
rather than raising, so it can never mask the original reason the node read
failed.

The manifest is required — losing it in both places still raises
`FileNotFoundError`. The progress log is best-effort.

To make the log recoverable at all, `add_task` now accepts `file_pattern` as a
string **or a list**, emitting one `OutputFile` per pattern, and imagery submits
both `outputs/*.*` and `logs/*.*`. A single blanket `**/*` was rejected: it would
also upload the raw downloaded imagery.

### 4. Stop destroying the status history

The imagery queue trigger appends via `MetadataUtils.append_status_message`
instead of assigning, and renders the cause through a new
`hastegeo.core.utils.errors.describe_exception`, which reduces an Azure-style
error to `NodeNotReady: Node is not able to perform the requested operations in
its current state`. It matches the error *shape* (`.error.code` /
`.error.message.value`) rather than importing `azure.batch`, so it stays a leaf
utility.

## Non-goals

- **Pool configuration.** Deallocation policy, `minNodes` and spot-vs-dedicated
  are untouched; this change makes the race survivable, not impossible.
- **Raising `maxDequeueCount`.** Redelivery would re-run whole tasks.
- **Blob fallback for other workloads.** The runner-level fixes cover them; only
  imagery reads a required output file back. `EmbeddingPostprocessor` also
  treats its manifest as required, so an embedding job whose node vanished still
  fails — a known gap, tracked in [plan.md](plan.md#open-questions), not a
  regression.

## Agent assignment

| Area | Implements | Validates |
|---|---|---|
| `hastelib/` runner, processor, utils | `backend-dev` | `backend-validation` |
| `api/hastefuncqueues/` status messages | `backend-dev` | `backend-validation` |
| Docs + spec | `backend-dev` | `orchestrator` |

## Acceptance criteria

1. A `NodeNotReady` response is retried rather than failing the layer.
2. When the node is gone for good, the manifest is recovered from blob and the
   layer completes normally.
3. An unreachable progress log never fails an otherwise successful layer.
4. Cleanup against a dead node does not fail the workload, and the job is still
   disabled.
5. Losing the manifest in both places still fails the layer, with a readable
   message.
6. A failure appends to `statusMessage`; it never replaces the history.
7. Unrelated Batch errors still propagate unchanged.

## Document index

| Document | Purpose |
|---|---|
| [design.md](design.md) | Technical design, call paths, contracts |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius |
| [user-stories.md](user-stories.md) | Stories, acceptance criteria, agent map |
| [test-plan.md](test-plan.md) | Test strategy and coverage matrix |
| [plan.md](plan.md) | Execution plan and task status |
| [rollout.md](rollout.md) | Rollout, verification, rollback |

## Decision log

| Decision | Rationale |
|---|---|
| Widen the retry predicate rather than add a second decorator | `apply_retry_to_methods` already wraps every `AzureBatchJob` method |
| Leave `reraise` at its default and unwrap `RetryError` at the boundary | wrapped methods call one another; re-raising a retryable error would multiply the budget 5× |
| Return `None` for an unreachable file | matches the existing contract; callers already branch on falsy content |
| Fall back via `get_file_remote_path` + HTTP | resolves the exact path Batch uploaded to, with no data-layer signature changes |
| `file_pattern` accepts a list | targeted; avoids a `**/*` upload of raw imagery |
| Duck-type the error shape in `utils.errors` | keeps a leaf utility free of an `azure.batch` import |
