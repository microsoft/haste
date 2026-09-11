# Local compute lifecycle

**Status:** implemented

**Date:** 2026-09-10

**Priority:** P0

## Contents

- [Scope](#scope)
- [Acceptance](#acceptance)
- [Live verification](#live-verification)
- [Documents and boundaries](#documents-and-boundaries)

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

## Live verification

Two isolated diagnostic PyTorch/TensorBoard jobs were observed through the
application API at `InProgress` with 25% progress while their Docker
containers were running. The second waited for the one-job host limit.
A queue-host restart did not duplicate either execution; both completed at
100% with outputs persisted and task files cleaned.

A separate fresh imagery queue run verified COG pixels/CRS, the Azurite
manifest, friendly logs, and labeling. These checks did not change normal
training parameters or run scientific model-quality validation.

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
