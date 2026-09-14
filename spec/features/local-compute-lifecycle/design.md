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

New receipts pin the credential-free storage account/endpoint as well as
the output container. Reconciliation rejects a changed account instead of
uploading an accepted execution into a different environment. Older
receipts remain readable and idempotent; keep their original storage
configuration until they are drained.

`LocalRunner.submit` returns the corresponding neutral compute handle.
Canonical `HASTE_JOB_WORKDIR` and legacy workspace variables are derived at
container launch, rather than persisted as caller-supplied environment.

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
reservation labels identify its execution and configured limit. Reservations
run no workload and acquire no GPU. Conflicting active capacity policies fail
explicitly; change the limit after draining active work.

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
are also persisted. Internal artifact-packaging staging links are not output
files. Selected output symlinks and paths escaping the workspace fail
explicitly.

`outputs_persisted` starts false. It becomes true only after all required
uploads succeed. Restart during upload repeats idempotent overwrites without
rerunning compute. Upload failure records an explicit failed receipt with
`outputs_persisted=false` and retains all local evidence.

Cleanup records intent but deletes task files only for terminal receipts
with proven persistence. Receipts remain as durable idempotency tombstones.
A cleanup call cannot discard outputs after failed persistence.

Local worker images prepare their own output permissions before exiting.
The queue process and training image can use different UIDs, so readable
files alone are insufficient: output directories must also permit the
queue process to remove their contents after persistence. The local-only
`HASTE_LOCAL_SHARED_WORKSPACE` flag is injected by the adapter, not accepted
from a task request. Image exit hooks grant group/other read access to owned
files and traversal/removal access to owned directories within that exact
job/task subtree, without following symlinks. Batch/AML permissions are
unchanged, and permission preparation failure cannot turn a failed job into
success.
Interrupted workers and older receipts may lack that exit preparation.
Before persistence or cleanup, the controller checks its own access and,
only when needed, runs the same scoped helper under the original image's
user. This helper has no network, GPU, or Linux capabilities, a read-only
container filesystem, and bounded CPU/memory; it never reruns the workload.
The controller rechecks permissions before declaring persistence or cleanup
successful.

Cancellation records intent under the short receipt lock and stops the
owned Docker container. Launch and cancellation are serialized. A cancel
during staging prevents launch; a cancel during upload wins over later
completion. Already committed terminal results remain terminal. Cancellation
never targets an unrelated container or treats a status-file edit as a stop.

## Metadata and queue recovery

Queue payloads are wake-ups, not authoritative document snapshots. Pending
identities are allocated in the existing job models and persisted before
messages are sent. Consumers load the current document, check the attempt,
and claim a revision-fenced processing turn. An expired claim permits
restart recovery; an old claim cannot publish state.

Processing claims renew while a turn is active. This heartbeat owns only a
coordination lease, not compute execution; a lost or superseded claim fences
the writer. Different follow-on requests wait for an occupied target rather
than acknowledging another job as their own.

Pending identities contain no provider job ID or fabricated Batch handle.
Once submission succeeds, the real handle is saved under the current
attempt even if cancellation arrived during submission. A late handle
cannot revive a terminal result or overwrite a newer attempt. Cleanup is
recorded with that full handle and deferred until the fenced metadata
commit succeeds. Backend/profile dispatch therefore survives configuration
changes and supports local, Batch, and AML consistently.

Only workload-owned runtime fields are merged back. New attempts,
cancellation intent, terminal outcomes, other workloads, and user edits
survive stale messages and racing callbacks. Follow-on work is recorded
durably so a failed queue send does not silently lose inference or zipping.

The publishing repository's revision-plus-lock boundary is prior art.
Metadata uses a shared conditional-update primitive instead of publishing
leases: Blob ETags, Cosmos ETags, PostgreSQL MVCC conditional writes, and
kernel-locked atomic local files. ADLS Gen2 metadata uses its same file's
Blob API with conditional writes; this is not a fallback storage account.
All metadata merge/save operations use that boundary for JSON. Unsupported
operations and storage errors fail explicitly; nothing depends on
`publishing_enabled` or on an additional lock service.

Two independent Function timers drive recovery. Every 15 seconds, one
reconciles existing local receipts, including queued work and interrupted
staging/uploads, even if the configured default backend has changed. The other,
every 30 seconds,
re-enqueues current pending/running/cancelling records and unfinished
follow-ons by their persisted backend. This second path closes gaps before
receipt creation and after
lost queue sends, independently of `maxDequeueCount=1`. Slow staging does not
block metadata polling or cancellation delivery. Neither timer owns compute
in memory, and both resume on a new Function worker.

## Configuration and rollout

| Setting | Default | Meaning |
|---|---|---|
| `COMPUTE_BACKEND_DEFAULT` / `RUNNER_TYPE` | Existing default | Submission preference; existing handles retain their backend |
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
To change the host limit, drain all local work, remove the verified
`haste-local-capacity` policy container, and configure the same new limit
on every controller before accepting more work. A conflicting live policy
fails explicitly rather than weakening the admission bound.

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
from telemetry. The backend-neutral/AML feature must preserve pending
identity, current-attempt fencing, deterministic Docker reconciliation,
host admission, and the cleanup/persistence invariant.
