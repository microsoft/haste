# UI Lifecycle Optimization

## Status

`implemented`

## Goal

Stop obsolete UI reads and resource-heavy work when users navigate away, and
reduce the initial JavaScript required for the first route.

## Scope

- Propagate `AbortSignal` through the shared UI API client.
- Cancel route-owned reads during effect cleanup.
- Prevent duplicate and overlapping project polling.
- Dispose Azure Maps resources when map routes unmount.
- Lazy-load route components.
- Avoid global layout updates when the responsive breakpoint is unchanged.

## Components

| Area | Implementing agent | Validating agent |
|---|---|---|
| `ui/src/util/api.js` and route components | `ui` | `ui-validation` |
| UI unit tests and production build | `ui` | `ui-validation` |

## Acceptance Criteria

- Navigating away aborts in-flight route-owned GET requests.
- Aborted requests do not surface user-facing errors.
- Project details load once on mount and polling requests do not overlap.
- Project and publishing polling pauses while the document is hidden.
- Visualizer maps and swipe controls are disposed on unmount.
- Heavy routes are emitted as separate production chunks.
- Existing API helper call sites remain source-compatible.
