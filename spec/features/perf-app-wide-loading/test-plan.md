# Test Plan: App-Wide Loading Performance

## Contents

- [Test Strategy](#test-strategy)
- [Regression Matrix](#regression-matrix)
- [Projects Cancellation Regressions](#projects-cancellation-regressions)
- [CXL-01 Browser Regressions](#cxl-01-browser-regressions)
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
| LOAD-01 | Blocking action plus lazy route | One visible status surface |
| LOAD-02 | Navigate during route GET | Request aborts; destination is unaffected |
| LABEL-01 | Current image layer has label pointer | Direct label read; no partition scan |
| LABEL-02 | Legacy or dangling label pointer | One compatible partition fallback |
| LABEL-03 | Standard Labeling Tool startup | Workspace and Maps begin concurrently |
| LABEL-04 | Map initialization succeeds | Loader remains until map/drawing readiness |
| LABEL-05 | Navigate during map initialization | Request aborts and map is disposed |
| HOME-01 | Optional catalog is slow | Dashboard renders without waiting |
| JOBS-01 | Dashboard has multiple projects | One compact Active Jobs request |
| JOBS-02 | Active Jobs poll is hidden or in flight | No new request |
| JOBS-03 | Matching Active Jobs ETag | Existing jobs retained after `304` |

## Projects Cancellation Regressions

The colocated spec tool mounts the real Projects component, row/card controls,
Fluent UI, and route-loading CSS in React StrictMode. Two additional scenarios
mount real Home and Projects without StrictMode to check inherited controls on
route entry. It uses isolated local HTTP fixtures and its own temporary Vite
cache. It never calls Dev1 or changes production authentication.

```bash
NODE_PATH=/path/to/playwright/node_modules node --test \
	spec/features/perf-app-wide-loading/tools/projects_cancellation.test.cjs
```

Use an existing external Playwright installation with its Chromium browser.
Optional `PROJECTS_OUTPUT_DIR` writes desktop/mobile screenshots outside the
repository; `PROJECTS_UI_ROOT` selects a different checkout for baseline checks.
The test server and browser close at the end of the run.

| Scenario | Required Evidence |
|---|---|
| Home to Projects with a pending or failed read, without StrictMode | Dashboard Help and tour clear on entry; success or Retry installs Projects controls without global loading writes |
| Five interrupted visits followed by return | Signals abort, actual HTTP reads close, no abandoned global loader writes, fresh read succeeds |
| Obsolete success/failure with non-cooperative transport | Destination header, tour, and explicit-action overlay remain intact; neither the new pending loader nor its successful data is replaced |
| HTTP failure, malformed response, and Retry | Local errors are visible, each retry gets a fresh read, success renders content |
| Shared country-data request across navigation | Departed consumer does not cancel the transfer; next consumer receives the result with one network fetch |
| Empty list | Successful empty state with no retained loader or error |
| Preference save followed by navigation | User-setting write remains un-aborted and its stored setting updates |
| Post-delete row and card refresh | Both callers retain an awaitable refresh; action overlay remains until the refresh completes, with no duplicate visible loader |

Actual abort assertions observe browser request failure and server stream
closure, not Playwright `route.abort()`. Separate deferred promises intentionally
ignore abort to verify stale-result guards. Expected simulated failure logs are
allowed; unhandled page exceptions fail the tests. Responsive loading/error
screenshots supplement these assertions; no backend latency improvement is
inferred from local fixture timings.

## CXL-01 Browser Regressions

Use the existing Node and external Playwright tooling. The harness starts and
stops its own ephemeral Vite/HTTP servers, mounts real components in StrictMode,
and never changes production authentication or contacts partner services.

```bash
node --test ui/src/Components/ProjectManagement/imagePreload.test.js
NODE_PATH=/path/to/playwright/node_modules node --test \
	spec/features/perf-app-wide-loading/tools/cxl01.test.cjs
```

Playwright and its Chromium binary must already be installed in the external
tooling directory. No application dependency change is required. Optional
`CXL_OUTPUT_DIR` writes desktop loading and mobile error screenshots outside
the repository. `CXL_UI_ROOT` can point at an untouched worktree for a negative
baseline run; the default is this checkout's UI.

| Scenario | Evidence |
|---|---|
| Navigate during ImageLayer body read, then return | Real browser request failure with abort; server closes stream; destination unaffected; fresh read succeeds |
| Change only layer ID with late responses | Deliberately non-cooperative transport cannot apply the obsolete result |
| HTTP failure or missing layer, then Retry | Local error ends loading; fresh attempt succeeds without global loader writes |
| Navigate/change thumbnail URL during transfer | Real streamed image fetch aborts; old URL is released |
| Empty, failed, cached and repeated thumbnail URLs | No stuck loader; each allocated Blob URL is revoked once after use |
| Cross-origin image with/without CORS | Abortable Blob path or native compatibility path displays as appropriate |
| Real LayerRow and LayerCard consumers | Both use returned Blob URLs and release them on departure |
| Checked-in CSP | Same-origin fetch and decoded Blob display succeed under the actual policy |

The harness observes application-triggered cancellation; it does not use
Playwright `route.abort()` to simulate it. Unit tests additionally cover abort
during body decoding, late native callbacks, decode failures, and suppression
of fallback after cancellation. Direct no-CORS fallback transfer cancellation
and actual authenticated Dev1 imagery are not claimed by these synthetic tests.

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