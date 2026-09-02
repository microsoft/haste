# Execution Plan: App-Wide Loading Performance

## Contents

- [Slices](#slices)
- [Exit Gates](#exit-gates)
- [Agent Summary](#agent-summary)

## Slices

| Slice | Task | Agent | Dependencies | Story | Status |
|---|---|---|---|---|---|
| 1 | Concurrent map/module loading, visible fallbacks, lazy help media | `ui` | Existing PR #189 | US-003 | implemented |
| 2 | Session bootstrap processor and thin API route | `backend-dev` | ADR-0005 | US-001 | implemented |
| 3 | UI bootstrap and independent request fan-out | `ui` | Slice 2 | US-001, US-003 | implemented |
| 4 | Published-dataset TTL/ETag cache and safe polling | `backend-dev`, `ui` | Slice 2 | US-002 | implemented |
| 5 | All-route deterministic performance matrix | `backend-dev`, `ui` | Slices 1-4 | US-004 | in-progress |

Each slice is reviewable and testable independently. No infrastructure or
dependency changes are planned.

## Exit Gates

- [x] Stable startup: one API call and zero user writes.
- [x] Feature-specific core, API, and UI regression tests pass.
- [x] Full `hastelib`, API, queue, and UI suites pass.
- [x] UI lint for changed files and production build pass.
- [ ] Dev1 route matrix records cold/warm direct and in-app timings.
- [ ] Function runtime ingress is restricted to trusted SWA/APIM traffic.
- [ ] No route exceeds the three-second p95 acceptance limit without a
  documented data-volume exception.

## Agent Summary

| Agent | Responsibility |
|---|---|
| `backend-dev` | Core session/cache logic and API wrappers |
| `backend-validation` | Core/API regression and contract validation |
| `ui` | Route, bootstrap, polling, and loading-state implementation |
| `ui-validation` | Browser route matrix and UI regressions |
| `orchestrator` | Track slice and spec status |