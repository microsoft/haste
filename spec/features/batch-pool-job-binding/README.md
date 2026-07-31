# Batch job / pool binding

**Status:** in-progress
**Type:** modification (fix)
**Supersedes:** the `_rebind_job_pool` approach in
[`../batch-config-drift/`](../batch-config-drift/)
**Related:** [`../batch-compute-expansion/`](../batch-compute-expansion/)
(capacity-aware routing)

## Problem

Two image layers submitted close together. The first ran; the second failed
before reaching Batch:

```
Job <h100-pool> is bound to pool <h100-pool> but this task targets pool
<t4-pool>, and rebinding failed (OperationInvalidForCurrentState).
```

Capacity-aware spillover therefore broke in exactly the concurrent case it
exists to serve.

## Root cause

Three properties collide:

1. **The Batch job id is static** — it comes from configuration and defaults to
   the singular pool id (`config.py`, `*_BATCH_JOB_ID`).
2. **The pool is chosen per task** — `select_pool` returns the first candidate
   with an idle node.
3. **A Batch job is permanently bound to one pool** — it can only be re-pointed
   while it has no active tasks.

| Step | Result |
|---|---|
| Task A | `t4` has no idle node → routed to `h100`; job created **bound to h100** |
| Task B (while A runs) | `h100` busy, `t4` idle → routed to **t4** |
| | Same static job id, but that job is bound to `h100` |
| Rebind attempt | `OperationInvalidForCurrentState` — job has active tasks |
| | Submission fails |

Rebinding was the wrong remedy: **one static job id cannot span multiple
pools**, and the moment concurrency exists it cannot be rebound.

## Design

**One job per pool.** `resolve_job_id(base, selected_pool, candidates)` in
`hastegeo.core.utils.batch_config` derives the job id from the routed pool:

| Case | Result |
|---|---|
| `base` is one of the candidate pool ids (the default convention) | the selected pool id |
| single candidate | `base` unchanged — legacy environments are not renamed |
| multiple candidates + custom `base` | `"<base>-<selected_pool>"`, trimmed to 64 |

Truncation removes characters from **`base`**, never the pool, so two different
pools can never collapse onto the same job id under the 64-character Batch
limit.

`AzureBatchJob.create_job` is now **graceful and returns the job id it actually
used**: it reuses a job whose binding already matches, rebinds one that is idle,
and otherwise falls back to a pool-scoped job instead of raising.

### Callers must capture the returned job id

`add_task` returns `(job_id, task_id)`, and the returned id may differ from the
one passed in. All five processors persist `jobId` into metadata, which is later
used for status polling and log retrieval, so each captures the returned value:
`imagery`, `train`, `inference`, `artifacts`, `embedding`.

## Non-goals

- Changing `select_pool`'s routing policy.
- Job cleanup/retention: jobs left bound to deleted pools are simply no longer
  selected, and Batch retention handles them.

## Agent assignment

| Area | Implements | Validates |
|---|---|---|
| `hastelib/` runner + processors | `backend-dev` | `backend-validation` |
| Docs + spec | `backend-dev` | `orchestrator` |

## Acceptance criteria

1. A task routed to a spillover pool uses a job scoped to that pool.
2. Single-candidate environments keep their existing job id.
3. Resolved job ids never exceed 64 characters, and remain distinct per pool.
4. `create_job` never fails a submission over a recoverable pool mismatch.
5. Processors persist the job id actually used, so status polling resolves.
