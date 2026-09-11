# App-Wide Loading Performance

**Status:** in-progress
**Author:** prbatero
**Date:** 2026-09-02
**Priority:** P1

## Contents

- [Summary](#summary)
- [Measured Baseline](#measured-baseline)
- [Success Criteria](#success-criteria)
- [Components](#components)
- [Documents](#documents)

## Summary

Bring every HASTE route to useful content in about two seconds, with a hard
target band of one to three seconds. This work removes shared startup waits,
optimizes published-dataset reads and polling, overlaps map and route loading,
and adds deterministic route-level performance coverage.

## Measured Baseline

Application Insights for dev1 after deployment `1.0.40rc3` showed:

| Operation | p50 | p95 | Finding |
|---|---:|---:|---|
| Global `GetUserById` | 1.17 s | 1.87 s | Serial startup dependency |
| Global `PutUser` | 0.87 s | 1.01 s | Unconditional startup write |
| `GetDashboardData` | 19 ms | 81 ms | Endpoint is already fast |
| `GetPublishedDatasets` | 0.98 s | 1.89 s | Leaves little UI budget |
| `GetProjectDetails` | 0.12 s | 2.27 s | Existing optimization remains |

Cold Azure Maps assets added about 1.82 seconds before route code and data.
Non-map lazy-route JavaScript added at most 63 KiB gzip, so API and asset
waterfalls dominate bundle transfer.

## Success Criteria

- [ ] Stable authenticated startup uses one API request, no management-plane
  user lookup, and no ACL write.
- [ ] Non-map routes reach useful content within 2 seconds at p50 and 3 seconds
  at p95 in the dev1 browser matrix.
- [ ] Map routes show useful shell/progress within 2 seconds and usable map
  controls within 3 seconds at p95 on a warm CDN cache.
- [ ] `GetPublishedDatasets` warm p95 is below 750 ms and conditional polls
  return `304` when unchanged.
- [ ] Hidden tabs and in-flight requests do not start another poll.
- [ ] Every navigable route has deterministic cold/warm and direct/in-app
  timing coverage.

## Components

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/` | Session bootstrap and bounded caches |
| `api/hastefuncapi/` | Thin bootstrap and conditional-list routes |
| `ui/src/` | Startup, route loading, polling, and progressive readiness |
| `spec/features/perf-app-wide-loading/` | Performance contract and results |

No new Azure resources, dependencies, queues, or persistent schemas are added.

## Documents

| Document | Purpose |
|---|---|
| [design.md](design.md) | API, cache, route, and security design |
| [plan.md](plan.md) | Ordered implementation slices |
| [impact-analysis.md](impact-analysis.md) | Risk and rollback analysis |
| [user-stories.md](user-stories.md) | Acceptance criteria and agent mapping |
| [data-model.md](data-model.md) | Response and cache data shapes |
| [test-plan.md](test-plan.md) | Regression and performance matrix |
| [rollout.md](rollout.md) | Dev1 validation and rollback |
| [results.md](results.md) | Live baseline and validation status |

## Related Specs

- [Project layer-loading performance](../perf-layer-loading/README.md)
- [Session bootstrap and revocation ADR](../../architecture/decisions/0005-session-bootstrap-and-revocation.md)