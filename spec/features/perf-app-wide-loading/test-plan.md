# Test Plan: App-Wide Loading Performance

## Contents

- [Test Strategy](#test-strategy)
- [Regression Matrix](#regression-matrix)
- [Performance Matrix](#performance-matrix)
- [Sign-Off](#sign-off)

## Test Strategy

| Level | Scope | Tool | Target |
|---|---|---|---|
| Unit | Session, cache, route helpers | `unittest`, Node test runner | Branch coverage for state transitions |
| API | Bootstrap and conditional list routes | Azure Functions test harness | Exact status/body/header contracts |
| UI | Startup, loading, ETag, polling | Node tests | Deterministic promise and timer control |
| Browser | Every route | Playwright | Cold/warm direct and in-app timings |

## Regression Matrix

| ID | Scenario | Expected |
|---|---|---|
| BOOT-01 | Stable active principal | One ACL read; no write or management call |
| BOOT-02 | Deleted/inactive principal | Roleless status response; no reactivation |
| BOOT-03 | Role mismatch | Least-privilege role intersection |
| PUB-01 | Concurrent identical list requests | One repository read per process |
| PUB-02 | Matching ETag | Empty `304` response |
| PUB-03 | Mutation then list | Cache invalidated |
| POLL-01 | Hidden tab | No poll |
| POLL-02 | Request in flight | No overlapping poll |
| MAP-01 | Cold map route | Module and map loading overlap |
| MAP-02 | Asset failure then retry | Loader resets and retries safely |
| HELP-01 | Help route | Images lazy; videos do not preload |

## Performance Matrix

For each route, record direct cold, direct warm, in-app cold, and in-app warm
on desktop and mobile profiles. Capture shell-ready, content-ready, API time,
map-ready, request count, transferred bytes, and failures.

| Route class | p50 goal | p95 limit |
|---|---:|---:|
| Non-map data route | 2 s | 3 s |
| Static/help/admin route | 1 s | 2 s |
| Map route shell | 2 s | 3 s |
| Map controls, warm CDN | 2 s | 3 s |

The Interactive Labeler shell and progress surface use the three-second route
gate. Complete readiness is reported separately by PMTiles/sidecar byte size;
the measured artifact proxy p95 exceeds the universal route budget.

Synthetic fixtures must contain projects, models, labels, validation records,
published datasets, and active/terminal jobs. Tests do not call partner APIs.

## Sign-Off

- [x] Focused tests pass after each slice.
- [x] Full backend, API, queue, and UI tests pass.
- [x] Changed-file lint and production build pass.
- [ ] CI security checks pass.
- [ ] Dev1 route matrix is recorded with no unexplained p95 over 3 seconds.