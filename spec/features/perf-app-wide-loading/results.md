# App-Wide Performance Results

## Contents

- [Baseline](#baseline)
- [Implemented Changes](#implemented-changes)
- [Expected Impact](#expected-impact)
- [Local Verification](#local-verification)
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
tests, 6 queue-trigger tests, and 161 UI tests passing. The production UI build
transformed 2,423 modules in 399 ms.

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

## Open Validation

- Deploy only after trusted Function ingress is enforced.
- Run `tools/route_matrix.cjs` with an authenticated storage state outside the
  repository and representative project/layer/model fixtures.
- Record desktop/mobile cold-direct, warm-direct, cold in-app, and warm in-app
  results.
- Re-query Application Insights for bootstrap and published-list p50/p95.
- Treat Interactive Labeler shell/progress as the three-second route gate;
  report complete artifact/map readiness against artifact byte size separately.