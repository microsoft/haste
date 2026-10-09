# User stories: local compute lifecycle

## Stories and acceptance

| Story | User need | Acceptance |
|---|---|---|
| US-001 | An analyst sees accepted work before it finishes. | Submission returns without staging/wait/upload; preparing, running, and uploading are nonterminal. |
| US-002 | An operator can restart workers without duplicate compute. | Duplicate/racing submissions resolve to one receipt/container; a fresh worker resumes staging, execution inspection, and uploads. |
| US-003 | An operator bounds local resource use. | Default active count is at most one per Docker host; excess accepted receipts eventually acquire released capacity. |
| US-004 | An analyst can cancel the intended execution. | Pending cancellation prevents launch; running cancellation stops the correct container; finish/cancel races cannot resurrect work. |
| US-005 | An analyst never receives false success or loses the only outputs. | Missing status is not success; successful exit waits for persistence; failed uploads remain explicit and files survive cleanup. |
| US-006 | An analyst's edits and newer attempts survive stale messages. | Conditional runtime writes fence attempts and processing revisions; terminal states and cancel intent cannot regress. |
| US-007 | An operator does not rely on automatic queue retries. | Timers recover accepted receipts, pre-submit metadata, poison delivery, and unfinished follow-ons after worker failure. |

## Agent Assignment Map

| Story | Implementing agent | Validating agent |
|---|---|---|
| US-001 | `backend-dev` | `backend-validation` |
| US-002 | `backend-dev` | `backend-validation` |
| US-003 | `backend-dev` | `backend-validation` |
| US-004 | `backend-dev` | `backend-validation` |
| US-005 | `backend-dev` | `backend-validation` |
| US-006 | `backend-dev` | `backend-validation` |
| US-007 | `backend-dev` | `backend-validation` |

## Exclusions

No new compute abstraction, AML dependencies, Azure services, UI changes,
TensorBoard discovery/parser changes, training-budget changes, or scientific
model changes. Integration and publication belong to the parent workflow.
