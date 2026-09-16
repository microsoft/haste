# Local compute lifecycle

**Status:** implemented

**Date:** 2026-09-10

**Priority:** P0

## Scope

Make the existing local Docker runner accept jobs durably before staging,
execution, and output persistence finish. Preserve `BaseRunner` arguments,
the `(job_id, task_id)` return value, Batch callers, and existing artifact
paths. Add execution-fenced queue updates and restart recovery without new
Azure services.

Local output permission preparation is included: different queue/worker UIDs
must not prevent persistence-gated cleanup. Existing Batch method shapes
are retained; no AML SDK or backend-neutral compute types are required.

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
The later backend-neutral/AML feature adapts this implementation to its new
contract; this prerequisite imports none of that feature's types or modules.
Training parameters, sampling, losses, and model quality are unchanged.
