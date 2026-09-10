# Plan: local compute lifecycle

## Implementation

| Task | Agent | Dependencies | Story | Status |
|---|---|---|---|---|
| Record focused spec and ADR-0006 | `backend-dev` | Approved lifecycle decision | All | complete |
| Implement receipts, host admission, reconciliation, cancellation, persistence gating | `backend-dev` | Spec | US-001 through US-005 | complete |
| Add conditional metadata updates and execution fences | `backend-dev` | Spec | US-006 | complete |
| Wire pending identities, queue consumers, recovery timers, and follow-ons | `backend-dev` | Lifecycle and fences | US-007 | complete |
| Add deterministic lifecycle, backend-CAS, processor, and queue tests | `backend-dev` | Implementation | All | complete |
| Run targeted and broader relevant tests and formatting/lint | `backend-dev` | Tests | All | complete; API/lifecycle/compute coverage passes, known baseline exception below |

## Integration gates

| Task | Agent | Dependencies | Story | Status |
|---|---|---|---|---|
| Validate implementation against acceptance | `backend-validation` | Combined integration | All | complete for deterministic tests; live gate below |
| Validate disposable Docker execution and restart on a Docker-capable host | `backend-validation` | Approved local smoke environment | US-001 through US-005 | pending live verification |
| Preserve lifecycle/fencing seams in progress and backend-neutral prerequisites | `backend-dev` | Combined integration | All | complete |

The combined branch is validated in the existing local Docker environment
before any prerequisite PR split. No AML resource provisioning or live AML
execution is part of this local verification.

The broader library run identifies the pre-existing stale
`TestArtifactProcessor.test_zip` call to a removed method. Unrelated
imagery-runtime work in the working tree also requires its matching native
PROJ environment; those files are outside this change.
