# User Stories: App-Wide Loading Performance

## Contents

- [Stories](#stories)
- [Agent Assignment Map](#agent-assignment-map)
- [Out of Scope](#out-of-scope)

## Stories

### US-001: Fast Stable Session Startup

**As a** HASTE user, **I want** the application shell and my route to load
without redundant identity writes, **so that** every direct navigation starts
quickly.

**Acceptance criteria:** A stable active user causes one bootstrap API request,
zero management-plane calls, and zero ACL writes. Inactive, pending, or deleted
users receive no application roles and cannot reach protected routes.

### US-002: Responsive Published Dataset Tracking

**As a** contributor, **I want** published datasets to load and refresh without
repeated full reads, **so that** I can track work without page stalls.

**Acceptance criteria:** Same-query requests coalesce, unchanged conditional
requests return `304`, and polling stops while hidden or in flight.

### US-003: Progressive Route Readiness

**As a** disaster analyst, **I want** each route to show useful progress while
its data or maps load, **so that** navigation never appears frozen.

**Acceptance criteria:** Route and map assets overlap, the application shell
remains visible, independent requests overlap, and help media loads on demand.

### US-004: Enforced Route Performance Budget

**As a** maintainer, **I want** deterministic route timings, **so that** future
changes cannot silently regress the one-to-three-second target.

**Acceptance criteria:** Every route has cold/warm direct and in-app timing,
request counts, asset bytes, and content-ready evidence.

## Agent Assignment Map

| Story | Implementing Agent(s) | Validating Agent(s) |
|---|---|---|
| US-001 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| US-002 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| US-003 | `ui` | `ui-validation` |
| US-004 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |

## Out of Scope

- New Azure services or Function capacity changes.
- Distributed cache or push-notification transport.
- Persistent publishing index until bounded cached reads are remeasured.
- Blob policy provisioning changes without separate SAS regression coverage.