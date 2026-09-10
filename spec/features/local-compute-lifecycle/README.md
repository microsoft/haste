# Local compute lifecycle

**Status:** in-progress

**Date:** 2026-09-10

**Priority:** P0

## Scope

Make the existing local Docker runner accept jobs durably before staging,
execution, and output persistence finish. Preserve `BaseRunner` arguments,
the `(job_id, task_id)` return value, Batch callers, and existing artifact
paths. Add execution-fenced queue updates and restart recovery without new
Azure services.

The integrated implementation also preserves `ComputeRunner` and persisted
`ComputeJobHandle` dispatch. Pending records reserve an execution ID, not a
fictional provider job ID. Accepted handles are recorded before a queue
turn can finish, including when cancellation races with submission.

The default is one active local workload per Docker host. Excess accepted
work waits for capacity. Docker and persistent receipts, not a worker thread,
own execution truth.

## Acceptance

- Acceptance returns before input downloads, container execution, or uploads.
- Competing submissions and reconciliations cannot duplicate an execution
  or exceed the configured host capacity.
- Worker restarts and lost queue deliveries do not strand accepted work.
- Cancellation stops the correct container and cannot be undone by a poll.
- Success requires persisted outputs; upload failures retain task files,
  including when cleanup/finalization is requested.
- Queue updates preserve newer attempts, terminal state, cancellation, and
  user-owned fields.

## Documents and boundaries

| Document | Purpose |
|---|---|
| [Design](design.md) | Lifecycle, persistence, admission, recovery, compatibility |
| [Stories](user-stories.md) | Acceptance criteria and agent assignments |
| [Plan](plan.md) | Implementation and validation tasks |
| [ADR-0006](../../architecture/decisions/0006-durable-local-lifecycle.md) | Durable local execution decision |

The progress/log/UI prerequisite owns TensorBoard discovery and parsing,
training progress calculations, child log streaming, and UI changes.
The backend-neutral/AML feature is integrated with these lifecycle
invariants; finalization and cancellation follow the stored backend/profile,
not the current default runner.
Training parameters, sampling, losses, and model quality are unchanged.
