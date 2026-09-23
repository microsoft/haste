# App-Wide Performance Results

## Contents

- [Baseline](#baseline)
- [Implemented Changes](#implemented-changes)
- [Expected Impact](#expected-impact)
- [Local Verification](#local-verification)
- [Projects Cancellation Verification](#projects-cancellation-verification)
- [CXL-01 Local Verification](#cxl-01-local-verification)
- [Open Validation](#open-validation)

## Baseline

Application Insights for dev1 release `1.0.40rc3` supplied the server-side
baseline. Post-deployment request samples showed:

| Endpoint | Samples | p50 | p95 | Maximum |
|---|---:|---:|---:|---:|
| `GetDashboardData` | 32 | 19 ms | 81 ms | 2.18 s |
| `GetModelCatalog` | 27 | 20 ms | 2.16 s | 2.61 s |
| `GetPublishedDatasets` | 6 | 0.98 s | 1.89 s | 1.89 s |
| `GetUserById` | 19 | 1.17 s | 1.87 s | 1.87 s |
| `PutUser` | 19 | 0.87 s | 1.01 s | 1.01 s |
| `GetProjectDetails` | 1,797 | 0.12 s | 2.27 s | 3.16 s |

The legacy startup chain serialized `GetUserById`, `PutUser`, and
`GetPublishingProviders`. Cold Azure Maps asset loading took about 1.82 seconds
from the measurement host. Route JavaScript was not the dominant cost: lazy
route dependencies ranged from about 0.3 to 65 KiB gzip after the entry bundle.

`GetModelArtifact` is a separate data-volume path. Over seven days, 24
successful transfers had a 0.39-second median, 91.5-second p95, and 254-second
maximum. The Interactive Labeler downloads complete PMTiles and feature-sidecar
artifacts, so full map readiness cannot have a universal three-second limit.

## Implemented Changes

- One read-only `GetSessionBootstrap` call replaces stable-session user lookup,
  user write, and provider discovery.
- Principal roles are intersected with active ACL roles; stable SWA object IDs
  are bound during explicit admin reconciliation.
- Published dataset pages use a five-second bounded single-flight cache,
  ETags, conditional requests, mutation invalidation, and non-overlapping
  visible-tab polling.
- Route imports overlap Azure Maps loading. Independent Maps assets load in two
  concurrent phases with retryable failures.
- Create/Edit Image Layer no longer loads Maps until the catalog drawer opens.
- Home, layer-form, validation, and Interactive Labeler requests overlap where
  dependencies allow.
- Interactive Labeler PMTiles and sidecar transfers start concurrently and are
  both required for readiness.
- Help images decode lazily and videos use `preload="none"`.
- Required route failures render retry actions instead of blank content.
- Route benchmarks require route-owned readiness markers, enforce p95 limits,
  fail on browser/API errors, and omit authentication and fixture details.
- Dashboard content no longer waits for the optional model catalog. Route-owned
  requests abort on navigation, and global blocking actions suppress local
  loading surfaces.
- Ongoing Jobs uses one conditional `GetActiveJobs` request instead of one full
  project-details request per candidate project.
- The standard Labeling Tool loads its module, Maps capabilities, and one
  allowlisted `GetLabelingWorkspace` response concurrently. One staged loader
  remains visible through map readiness, drawing setup, AOI fitting, and a
  stable map frame.
- Map routes load only their required control, drawing, or swipe capabilities.
  Standard labeling no longer waits for the unused swipe extension.

## Expected Impact

The changes remove roughly two seconds of median server work from stable direct
startup and reduce cold map asset critical path from a serial sum to two
parallel phases. Published-list warm reads should become representation-cache
hits after authorization and return `304` when unchanged.

These are expected effects, not post-deployment measurements.

## Local Verification

The final local regression pass completed with 614 core tests, 79 HTTP API
tests, 6 queue-trigger tests, and 164 UI tests passing. The production UI build
transformed 2,424 modules in 381 ms.

Black, isort, and Flake8 passed for the five Python files added or updated by
this follow-up. ESLint passed for 26 changed or new UI files, the three route
benchmark scripts passed Node syntax checks, `git diff --check` passed, and the
configured `detect-secrets` hook reported no candidates across 46 feature-owned
files. The Python suites emitted only existing Pydantic v2 deprecation
warnings.

A mocked browser interruption test delayed Model Catalog and Active Jobs by two
seconds, then navigated from Dashboard to Help. Dashboard showed one spinner,
Help became ready in 38 ms, and both abandoned requests were aborted with no
remaining loader. A real Azure Maps invalid-auth test confirmed that standard
labeling retains one persistent retry surface, does not start its tour, and
raises no application lifecycle exception. Successful production Maps loading
still requires Dev1 validation with real credentials.

A deterministic direct-load trace paused session bootstrap, Dashboard data, and
Active Jobs independently. The session and Dashboard phases both displayed the
same single overall `Loading dashboard` spinner. After Dashboard content
rendered, that overall spinner cleared and the still-pending Active Jobs request
displayed its intended spinner inside the Ongoing Jobs box.

## Projects Cancellation Verification

The Projects-only CXL-05P follow-up, based on #210 (`3834fb4`), passed 169
existing UI/unit/request-failure tests on 2026-09-16. Eight new browser scenarios
passed (nine Node entries including their parent suite), covering repeated
interruptions, stale completions, retry, shared reference data, empty lists,
preference writes, and awaitable row/card deletion refreshes.

The production UI build completed in 411 ms. Scoped ESLint passes for Projects;
full UI lint reports 170 existing diagnostics (162 errors, eight warnings),
down from 173 after removing three unused imports in the touched component.
Desktop and mobile loading/error screenshots were inspected and fit without
overlap. Tests use synthetic local data and do not contact Dev1.

The original diagnostic probe reproduced five continuing requests and late
global header/tour/loading writes from abandoned Projects visits. The new
tests verify cancellation and zero global loading writes for automatic reads.
This evidence is independent of the earlier HAR network delays and Function
startup stalls; those are not claimed as resolved. Human review, CI, and an
authenticated Dev1 smoke test remain pending.

On 2026-09-17, the change was moved onto `main` (`2dad150`) after verifying
that its source tree matches the original #210 base. All 169 existing tests
and eight browser scenarios passed again on the new branch. The browser
runner uses an external Playwright installation; no application dependencies
were added or changed.

On 2026-09-23, #227 incorporated `main` (`86aa6f7`) after CXL-01 / #223
merged. The combined tree passed 178 UI/unit/request-failure tests and both
browser suites: eight CXL-01 scenarios and eight Projects scenarios. The
production build completed in 483 ms. Full UI lint reports 169 diagnostics
(161 errors, eight warnings). Both implementations and their browser tests
were preserved byte-for-byte; four shared spec conflicts were resolved by
retaining both follow-up sections. No application deployment was performed.

## CXL-01 Local Verification

On 2026-09-16, the isolated CXL-01 change based on #210 (`3834fb4`) passed
176 UI/unit/request-failure tests, including seven new thumbnail lifecycle
tests. Eight Playwright browser scenarios passed under React StrictMode
(nine Node test entries including their parent). The production UI build
transformed 2,425 modules and completed in 403 ms.

Scoped ESLint passes for the changed UI files, and documentation links and
`git diff --check` pass. Full UI lint still reports the existing 173-diagnostic
baseline (165 errors, 8 warnings); unrelated lint debt was not changed.

The same browser harness against untouched #210 failed its navigation assertion:
the ImageLayer request was not aborted. The candidate passes that assertion
and verifies late-response isolation, layer-ID replacement, retry, native
fallback, actual row/card consumers, Blob URL revocation, and CSP compatibility.
Desktop loading and mobile error screenshots were inspected for text fitting
and overlap. Tests emitted existing ImageLayer table-nesting warnings and
fixture/legacy prop warnings; no application lifecycle exceptions occurred in
the passing run.

Browser traffic was synthetic and local. This is not a measurement of Dev1
bandwidth savings, destination p95, or server-side cancellation. Cross-origin
native-image fallback remains best-effort cleanup, and a representative
authenticated Dev1 imagery smoke check is still required before rollout.
No deployment, branch rewrite, or backend change was performed.

## Open Validation

- Deploy only after trusted Function ingress is enforced.
- Run `tools/route_matrix.cjs` with an authenticated storage state outside the
  repository and representative project/layer/model fixtures.
- Record desktop/mobile cold-direct, warm-direct, cold in-app, and warm in-app
  results.
- Re-query Application Insights for bootstrap and published-list p50/p95.
- Treat Interactive Labeler shell/progress as the three-second route gate;
  report complete artifact/map readiness against artifact byte size separately.