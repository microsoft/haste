# User Stories: Batch node-loss resilience

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Domain expert who uploads imagery and interprets damage maps | Imagery processing that completes, and status text that explains itself |
| ML Engineer | Runs training and inference on Batch pools | Jobs that are not lost to infrastructure churn |

---

## Stories

### US-001: Imagery processing survives the node going away

**As a** Disaster Analyst,
**I want to** have my image layer finish processing even when the Batch node
that ran it is deallocated or preempted,
**So that** I am not forced to re-upload and re-run imagery that already
processed successfully.

**Priority:** P0
**Estimate:** M
**Component(s):** `hastelib/core/runners/azure_batch.py`,
`hastelib/core/processors/imagery.py`

**Acceptance Criteria:**

```gherkin
Given an imagery preprocessing task that completed successfully
And the compute node that ran it is transitioning (starting, rebooting)
When the processor reads imagery_manifest.json from the node
Then the read is retried
And the layer completes normally once the node answers
```

```gherkin
Given an imagery preprocessing task that completed successfully
And the node that ran it has been deallocated or preempted
When the processor reads imagery_manifest.json from the node
Then the manifest is read from the copy Azure Batch uploaded to blob storage
And the image layer is marked COMPLETED
```

```gherkin
Given an imagery preprocessing task whose manifest is available nowhere
When the processor tries the node and then blob storage
Then the layer is marked FAILED with a readable cause
```

**Notes:** The manifest is required for the layer to complete; the fallback path
is the recovery, not a silent skip.

---

### US-002: A lost progress log never fails a good layer

**As a** Disaster Analyst,
**I want** a missing progress log to cost me detail, not the whole layer,
**So that** infrastructure churn cannot discard imagery that was produced
correctly.

**Priority:** P1
**Estimate:** S
**Component(s):** `hastelib/core/processors/imagery.py`

**Acceptance Criteria:**

```gherkin
Given a completed imagery task
And imagery_friendly.log cannot be read from the node or from blob storage
When the processor collects progress records
Then no records are added
And the layer still completes
```

```gherkin
Given a completed imagery task whose node is gone
When the processor collects progress records
Then the log is read from blob storage
And its entries appear in the layer status history
```

**Notes:** Requires `logs/` to be included in the task's `OutputFile` patterns;
before this change the log existed only on the node.

---

### US-003: Failure messages stay readable and keep their history

**As a** Disaster Analyst,
**I want** the status dialog to show what went wrong in plain language, on top
of the progress that already happened,
**So that** I can tell whether the failure was mine (bad imagery) or the
platform's.

**Priority:** P1
**Estimate:** S
**Component(s):** `api/hastefuncqueues/function_app.py`,
`hastelib/core/utils/errors.py`

**Acceptance Criteria:**

```gherkin
Given an image layer that recorded progress messages
When processing fails with an Azure Batch error
Then the failure is appended to the existing status history
And it is rendered as "<Code>: <message>" without the SDK object dump
And without the RequestId/Time trailer
```

```gherkin
Given processing fails with a non-Azure exception
When the status message is written
Then it falls back to the exception's own text
And is never empty
```

---

### US-004: Post-task cleanup never fails a workload

**As an** ML Engineer,
**I want** working-directory cleanup against a dead node to be a no-op,
**So that** a completed training, inference, artifact or imagery job is not
marked failed by its own cleanup step.

**Priority:** P1
**Estimate:** S
**Component(s):** `hastelib/core/runners/azure_batch.py`

**Acceptance Criteria:**

```gherkin
Given a task whose node is no longer available
When cleanup_task runs
Then the working-directory delete is skipped with a warning
And the job is still disabled
```

```gherkin
Given cleanup fails with an error unrelated to node availability
When cleanup_task runs
Then the error propagates
```

**Notes:** Disk on a dead node is reclaimed by Batch; `task_retention_time` is
`P2D`.

---

## Agent Assignment Map

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend, API, processors, data layers, runners | Yes |
| `backend-validation` | Validates backend code against specs, conventions, tests | No (validates only) |
| `orchestrator` | Records what agents did, when, why. Tracks spec status. | No (observes only) |

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `backend-dev` | `backend-validation` | `hastelib/` runner + imagery processor |
| US-002 | `backend-dev` | `backend-validation` | Output-upload patterns + best-effort log read |
| US-003 | `backend-dev` | `backend-validation` | `api/hastefuncqueues/` + new `utils/errors.py` |
| US-004 | `backend-dev` | `backend-validation` | Runner cleanup path, all workloads |

> `gis` is **not** assigned: no imagery, GDAL or provider-adapter logic changes —
> only how already-produced outputs are retrieved.
> `ui` is **not** assigned: the status dialog renders `statusMessage` unchanged;
> only the text written into it improves.
> `security` is **not** assigned: no new dependencies.

### Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Phase 1 — Core Library | `backend-dev` | — | `backend-validation` |
| Phase 2 — Queue workers | `backend-dev` | — | `backend-validation` |
| Phase 3 — Docs & spec | `backend-dev` | — | `orchestrator` |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-001 | Phase 1 — Core Library | `backend-dev` | `hastelib` |
| P1 | US-002 | Phase 1 — Core Library | `backend-dev` | `hastelib` |
| P1 | US-003 | Phase 2 — Queue workers | `backend-dev` | `hastefuncqueues` |
| P1 | US-004 | Phase 1 — Core Library | `backend-dev` | `hastelib` |

## Out of Scope

- [ ] Changing the Batch pool's deallocation policy, `minNodes`, or
      dedicated-vs-spot node type — the race is made survivable, not impossible.
- [ ] Raising `maxDequeueCount` so failed queue messages are redelivered —
      redelivery would re-run whole tasks.
- [ ] A blob fallback for train/inference/artifacts/embedding — they inherit the
      runner-level fixes; only imagery reads a required output file back.
- [ ] Recovering image layers that already failed on dev1 — they must be re-run.
