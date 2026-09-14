# ADR-0006: Docker-backed durable local job lifecycle

**Status:** accepted

**Date:** 2026-09-10

**Deciders:** HASTE maintainers (approved implementation request)

## Context and alternatives

The synchronous local runner waits for container completion and uploads
before processors can publish an accepted identity. Long jobs therefore
remain queued in metadata. Wrapping that wait in a daemon thread would lose
staging, cancellation, and persistence ownership on worker restart.

UI timers cannot establish execution truth. A new orchestration service is
unnecessary for a local Docker host with existing shared storage and
Function timers. See the [feature design](../../features/local-compute-lifecycle/design.md).

## Decision

Persist atomically updated execution receipts on the existing shared task
volume and use deterministic, ownership-labelled Docker containers.
Unstarted Docker reservation containers provide race-safe host-wide
admission, defaulting to one active workload. Independent periodic
reconciliation advances queued receipts and recovers interrupted work.

Keep `BaseRunner` signatures and Batch compatibility. Gate success and
cleanup on required output persistence. Record cancellation durably and
stop the actual owned execution. Fence queue runtime writes with current
attempt identities, revisions, and storage-native conditional updates.
Use existing workflow logs rather than a separate local progress format.

## Consequences

Worker lifetime no longer defines job lifetime. Restart recovery does not
require secrets in receipts, another Azure service, or duplicate compute.
Receipts and admission reservations need durable retention and ownership
checks; deployment and rollback require draining legacy unnamed jobs.

The progress/log/UI implementation and the backend-neutral/AML contract
preserve these invariants together. See [ADR-0005](0005-backend-neutral-compute-runner-and-aml-backend.md)
for neutral handles and routing. Queue finalization and cancellation use the
persisted handle, while the local adapter owns Docker admission and receipts.
