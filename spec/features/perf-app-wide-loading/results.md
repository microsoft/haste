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

## Expected Impact

The changes remove roughly two seconds of median server work from stable direct
startup and reduce cold map asset critical path from a serial sum to two
parallel phases. Published-list warm reads should become representation-cache
hits after authorization and return `304` when unchanged.

These are expected effects, not post-deployment measurements.

## Local Verification

The final local regression pass completed with 601 core tests, 72 HTTP API
tests, 6 queue-trigger tests, and 148 UI tests passing. The production UI build
transformed 2,419 modules in 431 ms.

Black, isort, and Flake8 passed for the nine feature-owned Python files. ESLint
passed for 38 changed UI files, both benchmark scripts passed Node syntax
checks, `git diff --check` passed, and the configured `detect-secrets` hook
reported no candidates. The Python suites emitted only existing Pydantic v2
deprecation warnings.

## Open Validation

- Deploy only after trusted Function ingress is enforced.
- Run `tools/route_matrix.cjs` with an authenticated storage state outside the
  repository and representative project/layer/model fixtures.
- Record desktop/mobile cold-direct, warm-direct, cold in-app, and warm in-app
  results.
- Re-query Application Insights for bootstrap and published-list p50/p95.
- Treat Interactive Labeler shell/progress as the three-second route gate;
  report complete artifact/map readiness against artifact byte size separately.