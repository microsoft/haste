# User Stories: App-Wide Loading Performance

## Stories

### US-001: Fast Stable Session Startup

**As a** HASTE user, **I want** the application shell and my route to load
without redundant identity writes, **so that** every direct navigation starts
quickly.

**Acceptance criteria:** A stable active user causes one bootstrap API request,
zero management-plane calls, and zero ACL writes. Inactive, pending, or deleted
users receive no application roles and cannot reach protected routes.


### US-003: Progressive Route Readiness

**As a** disaster analyst, **I want** each route to show useful progress while
its data or maps load, **so that** navigation never appears frozen.

**Acceptance criteria:** Route and map assets overlap, the application shell
remains visible, independent requests overlap, and help media loads on demand.


### US-005: One Owned Loading Experience

**As a** HASTE user, **I want** navigation to show one coherent loading state,
**so that** progress does not flicker or remain blocked by work from a route I
already left.

**Acceptance criteria:** Route initialization uses local state, navigation
aborts owned GET requests and map work, and a stale route cannot clear or retain
the destination route's loading surface.


## Agent Assignment Map

| Story | Implementing Agent(s) | Validating Agent(s) |
|---|---|---|
| US-001 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| US-003 | `ui` | `ui-validation` |
| US-005 | `ui` | `ui-validation` |
