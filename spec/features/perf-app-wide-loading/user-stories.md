# User Stories: App-Wide Loading Performance

## Stories

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
| US-003 | `ui` | `ui-validation` |
| US-005 | `ui` | `ui-validation` |
