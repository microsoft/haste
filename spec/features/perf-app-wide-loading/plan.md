# Execution Plan: App-Wide Loading Performance

## Contents

- [Slices](#slices)
- [Projects Cancellation Follow-Up](#projects-cancellation-follow-up)
- [CXL-01 Follow-Up](#cxl-01-follow-up)
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
| 6 | Route-local loading and abortable GET lifecycle | `ui` | Slice 3 | US-005, US-007 | implemented |
| 7 | Labeling Workspace API and staged map initialization | `backend-dev`, `ui` | Slice 6 | US-006 | implemented |
| 8 | Compact cached Active Jobs API and polling | `backend-dev`, `ui` | Slice 6 | US-007 | implemented |

Each slice is reviewable and testable independently. No infrastructure or
dependency changes are planned.

## Projects Cancellation Follow-Up

CXL-05P extracts only the Projects list from the broader CXL-05 cancellation
work. Implementation was approved on 2026-09-16 and PR preparation on
2026-09-17. The independent branch originally started at `main` (`2dad150`),
whose source tree matches the original #210 base (`3834fb4`). On 2026-09-23,
`main` (`86aa6f7`) was merged into #227 after #223 landed, preserving both
CXL-01 and CXL-05P. Unrelated working-tree edits are unchanged.

| Task | Agent | Validating Agent | Story | Status |
|---|---|---|---|---|
| Abort departed/replaced Projects reads and suppress stale data/header/tour updates | `ui` | `ui-validation` | US-005 | implemented locally |
| Use local read loading/error/Retry and guard shared-country callbacks | `ui` | `ui-validation` | US-005 | implemented locally |
| Preserve preference-save and awaitable row/card delete-refresh contracts | `ui` | `ui-validation` | US-005 | verified locally |
| StrictMode, interrupted-navigation, error, shared-data, and action regression tests | `ui` | `ui-validation` | US-005 | passed locally |
| Clear inherited header/tour state on mount; test pending and failed Home-to-Projects entry without StrictMode | `ui` | `ui-validation` | US-005 | passed locally |
| Human review, CI and authenticated Dev1 smoke test | `ui` | `ui-validation` | US-005 | pending |

Other CXL-05 list/admin pages remain pending. This change is prepared as a
separate draft PR against `main`; it does not depend on #223. No application
deployment or live configuration change is included.
See [browser test commands](test-plan.md#projects-cancellation-regressions).

## CXL-01 Follow-Up

Prepared on 2026-09-16 as a separate change based on the cumulative #210 tip
`3834fb45e06910a03fb9a5680a26ee42605ace2f`. Implementation is isolated from the
reviewed performance branches and unrelated working-tree edits.

| Task | Agent | Validating Agent | Story | Status |
|---|---|---|---|---|
| Abort ImageLayer reads, guard stale results, use local loading and Retry | `ui` | `ui-validation` | US-005 | implemented locally |
| Abort thumbnail fetches, retain compatible native fallback, release Blob URLs | `ui` | `ui-validation` | US-005 | implemented locally |
| Unit, real-browser lifecycle, consumer integration, CSP and responsive checks | `ui` | `ui-validation` | US-005 | passed locally |
| Smoke-test representative authenticated Dev1 imagery | `ui` | `ui-validation` | US-005 | pending before rollout |

No backend, infrastructure, dependency, save, export, or job-submission changes
are included. CXL-01 was merged through #223 on 2026-09-23; the Projects-only
follow-up is tracked separately above. Other cancellation work packages remain
pending.
See [test commands](test-plan.md#cxl-01-browser-regressions) and
[verification results](results.md#cxl-01-local-verification).

## Exit Gates

- [x] Stable startup: one API call and zero user writes.
- [x] Feature-specific core, API, and UI regression tests pass.
- [x] Full `hastelib`, API, queue, and UI suites pass.
- [x] UI lint for changed files and production build pass.
- [ ] Dev1 route matrix records cold/warm direct and in-app timings.
- [ ] Function runtime ingress is restricted to trusted SWA/APIM traffic.
- [ ] No route exceeds the three-second p95 acceptance limit without a
  documented data-volume exception.
- [x] Interrupted navigation aborts route-owned GET and map work.
- [x] Standard Labeling Tool renders one staged loader through map readiness.
- [x] Dashboard renders before optional catalog and active-job requests finish.
- [x] Active Jobs uses one non-overlapping conditional request per poll.

## Agent Summary

| Agent | Responsibility |
|---|---|
| `backend-dev` | Core session/cache logic and API wrappers |
| `backend-validation` | Core/API regression and contract validation |
| `ui` | Route, bootstrap, polling, and loading-state implementation |
| `ui-validation` | Browser route matrix and UI regressions |
| `orchestrator` | Track slice and spec status |