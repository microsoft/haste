# Design: local compute lifecycle

## Contents

- [Contract and authority](#contract-and-authority)
- [Admission and execution](#admission-and-execution)
- [Persistence and cancellation](#persistence-and-cancellation)
- [Metadata and queue recovery](#metadata-and-queue-recovery)
- [Configuration and rollout](#configuration-and-rollout)
- [Validation and integration seams](#validation-and-integration-seams)

## Contract and authority

`LocalRunner.add_task` atomically creates or replays a versioned receipt and
returns the existing two-string identity. It performs no resource download,
container wait, or output upload. Receipts live outside task output trees on
the existing shared Docker volume. They survive task cleanup and contain
safe resource descriptors, execution identity, phases, cancellation intent,
and persistence evidence, never storage credentials or signed URLs.
Unsigned account identity and endpoint are bound to the receipt; credential
rotation through `Config` is allowed, but switching accounts cannot silently
redirect an accepted task.

Execution names are deterministic hashes of the job/task identity. Docker
labels fence container ownership. A repeated request with different launch
values fails rather than replacing accepted work. A cancellation tombstone
also prevents a late submission from starting cancelled work.

The phase sequence is `queued -> preparing -> running -> uploading ->
completed | failed | cancelled`. Preparation and upload remain nonterminal.
The legacy status API maps nonterminal phases to `InProgress`, keeping
processors in their polling branch; the receipt exposes the precise phase.
Lifecycle messages use the existing `timestamp|message` workflow log format.
Docker exit alone is never business success.

## Admission and execution

Unstarted, named Docker reservation containers act as host-wide capacity
slots. Docker's atomic name uniqueness serializes contenders even when
Function workers use different processes or shared-volume mounts. The
reservation labels identify its execution and configured limit. A separate
unstarted `haste-local-capacity` container pins one limit for the entire host,
preventing mixed controller settings from allocating different slot ranges.
Reservations and the policy container run no workload and acquire no GPU.

The default limit is one. A receipt reserves a slot before input staging and
keeps it through execution and required output persistence. Excess receipts
remain queued and are considered in acceptance order on each reconciliation.
Only the owning execution may release a reservation. Crash recovery reuses
both the reservation and the deterministic workload container.

Kernel file locks on the shared volume serialize each receipt's short
mutations and each task's longer reconciliation separately. No host-wide
lock spans staging or uploads. Atomic replacement and filesystem sync protect
receipt writes; kernel locks release on worker death.

The controller persists create/start intent before Docker side effects.
After a lost create/start response it inspects the same named container.
It starts only a never-started container; an exited execution is never
restarted. A missing previously started container is an explicit failure,
not permission to recompute.

## Persistence and cancellation

The reconciliation timer resumes partial staging, samples Docker logs
without following them, inspects execution state, and uploads task files
using existing storage paths. Authentication is resolved through `Config`.
Staging paths must remain inside the task directory. The output uploader
keeps the existing removal of the `outputs/` prefix.
Declared output patterns are retained in receipts; workflow and Docker logs
are persisted as well. Internal staging links are not output files.
Selected output symlinks and paths escaping the workspace fail explicitly.

`outputs_persisted` starts false. It becomes true only after all required
uploads succeed. Restart during upload repeats idempotent overwrites without
rerunning compute. Upload failure records an explicit failed receipt with
`outputs_persisted=false` and retains all local evidence.

The queue defers processor cleanup until its fenced metadata commit succeeds.
Cleanup then records intent but deletes task files only for terminal receipts
with proven persistence. Receipts remain as durable idempotency tombstones.
A cleanup call cannot discard outputs after failed persistence.

Local images and queues can have different UIDs. The adapter injects a
local-only workspace flag; image exit hooks prepare only owned files and
directories within the exact job/task subtree. Files gain read access, not
write access, and directories allow removal by the queue process.
Preparation uses inode-bound Linux descriptors and never follows symlinks.
For interrupted workers or older receipts, a bounded helper runs as the
original image user with no network, GPU, or capabilities and a read-only
container filesystem. Queue access is rechecked before persistence or
cleanup succeeds. Batch permissions are unchanged.

Cancellation records intent under the short receipt lock and stops the
owned Docker container. Launch and cancellation are serialized. A cancel
during staging prevents launch; a cancel during upload wins over later
completion. Already committed terminal results remain terminal. Cancellation
never targets an unrelated container or treats a status-file edit as a stop.
The top-level legacy `Cancelled` status records user intent. The nested job
status acknowledges the provider outcome only after the stop operation.
If completion already won, the nested status and message report that fact
instead of claiming the execution was stopped.

## Metadata and queue recovery

Queue payloads are wake-ups, not authoritative document snapshots. Pending
identities are allocated in the existing job models and persisted before
messages are sent. Consumers load the current document, check the attempt,
and claim a revision-fenced processing turn. An expired claim permits
restart recovery; an old claim cannot publish state.
Five-minute claims renew every minute during a processing turn. This small
coordination heartbeat neither runs nor schedules compute; losing it fences
the writer, and the persisted claim expires for independent timer recovery.

Ambiguous submission errors retain the pending IDs instead of marking
possibly accepted compute failed. Batch replay checks existing tasks across
the configured candidate jobs before capacity routing and accepts a same-job
`TaskExists` race without changing the legacy return shape.

Only workload-owned runtime fields are merged back. New attempts,
cancellation intent, terminal outcomes, other workloads, and user edits
survive stale messages and racing callbacks. Follow-on work is recorded
durably so a failed queue send does not silently lose inference or zipping.
Follow-ons have stable request keys. A different follow-on waits if its
target is busy; it cannot acknowledge another execution as its own work.
Imagery label generation uses an attempt-scoped deterministic ID and
create-only persistence, preserving labels already edited after a retry.

The publishing repository's revision-plus-lock boundary is prior art.
Metadata uses a shared conditional-update primitive instead of publishing
leases: Blob ETags, Cosmos ETags, PostgreSQL MVCC conditional writes, and
kernel-locked atomic local files. ADLS Gen2 metadata uses its same file's
Blob API with conditional writes; this is not a fallback storage account.
All metadata merge/save operations use that boundary for JSON. Unsupported
operations and storage errors fail explicitly; nothing depends on
`publishing_enabled` or on an additional lock service.

Two independent Function timers drive recovery. `ReconcileLocalTasks`
runs every 15 seconds, acts only for `local`, and reconciles receipts,
including queued work and interrupted staging/uploads. `ReconcileJobQueues`
runs every 30 seconds for the currently configured legacy runner and
re-enqueues current pending/running/cancelling records and unfinished
follow-ons. This second path closes gaps before receipt creation and after
lost queue sends, independently of `maxDequeueCount=1`. Slow staging does not
block metadata polling or cancellation delivery. Neither timer owns compute
in memory, and both resume on a new Function worker.

## Configuration and rollout

| Setting | Default | Meaning |
|---|---|---|
| `RUNNER_TYPE` | Existing default | Local reconciliation is gated; queue recovery respects persisted backend identity |
| `HASTE_LOCAL_MAX_ACTIVE_TASKS` | `1` | Host-wide active workload limit |
| `HASTE_DOCKER_AZURITE_VOLUME` | `docker_azurite-data` | Existing shared task volume |
| `HASTE_DOCKER_NETWORK` | `docker_default` | Existing workload network |
| `HASTE_DOCKER_MEM_LIMIT` | `32g` | Existing per-workload memory bound |
| `HASTE_DOCKER_SHM_SIZE` | `8g` | Existing shared-memory bound |
| `PRESERVE_LOCAL_TASK_DIRS` | `0` | Keep even safely persisted task files |
| `CLEANUP_CONTAINERS` | `1` | Remove stopped workloads after persistence |

Deploy only after draining legacy local jobs: legacy unnamed Docker
executions cannot be safely adopted or cancelled by identity. Missing
status files and old success files without persistence evidence do not
prove success. Keep the shared volume and deterministic container identities
across worker restarts. Do not remove reservation containers or receipts
while work is active. Roll back only after draining the new lifecycle.

Workers consuming one local deployment's queues must address the same Docker
daemon and mount the same task volume at `/shared/azurite`. Independent local
hosts need isolated deployment queues/metadata; this is not a multi-host local
scheduler. Independent deployments on one Docker host still share its
capacity policy.

To change the host limit, drain **all** local work, stop its controllers,
remove only the unstarted `haste-local-capacity` policy container, and restart
every controller with the same `HASTE_LOCAL_MAX_ACTIVE_TASKS` value.
Do not remove the policy while any controller can admit work.

## Validation and integration seams

Deterministic fake Docker/storage tests cover acceptance barriers, phase
transitions, host slots, competing submissions, response loss, worker
restart, cancellation races, missing execution evidence, partial persistence,
and cleanup retention. Metadata tests exercise conditional conflicts for
every supported backend and stale/terminal/user-edit fencing. Queue tests
cover all five workloads, lost delivery, poison recovery, and follow-ons.
Unit tests make no cloud/network calls.

The progress prerequisite must preserve receipt ownership, phase mapping,
and output-persistence gating when changing `get_filecontent_from_task`.
It may consume existing workflow logs but must not infer execution success
from telemetry. Lifecycle entries share `logs/workflow_progress.log`; no
new local progress schema is introduced. Processor queue sends and cleanup
must remain owned by the fenced queue boundary, not telemetry branches.
The backend-neutral/AML feature must preserve pending
identity, current-attempt fencing, deterministic Docker reconciliation,
host admission, and the cleanup/persistence invariant.
