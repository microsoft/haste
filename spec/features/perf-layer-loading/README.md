# Feature: Image Layer & Model Run Loading Performance

**Status:** draft
**Author:** prbatero
**Date:** 2026-08-03
**Target Release:** TBD
**Priority:** P1

## Summary

The HASTE UI takes too long to load a project's image layers and their associated
model runs, and the delay grows roughly linearly (in places quadratically) with the
number of image layers on a project. The root cause is a set of N+1 storage access
patterns in the `GetProjectDetails` API path, fully-sequential (never parallelized)
blob I/O in `hastelib`, full-container blob scans without prefix filtering, and a UI
that re-fetches the entire project — every model of every layer — every 20 seconds
while re-rendering the whole component tree. This spec catalogs the verified
bottlenecks and lays out a phased plan to make layer/run loading fast and roughly
constant-time regardless of project size.

## Motivation

- **Problem:** Disaster-response users open a project and wait many seconds for the
  layer list to appear; the wait scales with project size, so the most active
  (large) projects are the slowest — exactly when responders can least afford it.
- **Trigger:** Direct user report — "the HASTE UI takes too long to load image
  layers and their model runs when there are multiple image layers on a project."
- **Cost of inaction:** Load time degrades as projects accumulate layers and models;
  the 20s polling loop multiplies backend load and cost, and the app feels
  progressively slower the more it is used.

## Success Criteria

- [ ] `GET GetProjectDetails?includeModels=True` for a 50-layer / ~5-models-per-layer
      project returns in **< 1.5s p95** (from a current baseline measured in Phase 0).
- [ ] Backend storage round-trips for that request drop from **O(layers × models)**
      (~600 for the 50×5 case) to **O(1) small constant** (≤ ~6 partition reads).
- [ ] UI time-to-interactive for the project page is **< 2s p95** on the same project
      and no longer scales linearly with layer count.
- [ ] Background refresh no longer refetches unchanged data or re-renders the full
      tree; idle CPU and network on an open project page drop measurably.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/data_layer/` | Add prefix-scoped listing, parallel/metadata-only reads, fix double-deserialize |
| `hastelib/src/hastegeo/core/processors/` | `MetadataProcessor` filtered load + optional request-scoped cache |
| `hastelib/src/hastegeo/core/artifact_storage/` | Parallelize multi-blob fetch |
| `api/hastefuncapi/` | Rewrite `GetProjectDetails` layer loop; add cache headers |
| `api/hastefuncqueues/` | Parallelize independent loads; fix N+1 label lookup; batch saves |
| `ui/src/Components/` | Smart polling, memoization, split context, lazy model expansion |

## Related Specs

| Spec | Relationship |
|---|---|
| [../batch-config-drift/](../batch-config-drift/) | related (queue/Batch path) |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [findings.md](findings.md) | Verified bottleneck inventory with file:line evidence | draft |
| [design.md](design.md) | Technical design of each fix | draft |
| [plan.md](plan.md) | Phased execution plan | Phase 0 done |
| [impact-analysis.md](impact-analysis.md) | Risk, blast radius, backward compat | draft |
| [test-plan.md](test-plan.md) | Benchmark harness & regression coverage | draft |
| [results.md](results.md) | **Phase 0 measured baseline** (603 round-trips, 20.8 s API, 40.3 s UI TTI @ 50×5) | done |
| [tools/](tools/) | Seed + benchmarks: `phase0_baseline.py`, `bench_api_http.py`, `ui_bench.cjs`; `docker/docker-compose.perf.yml` overlay | done |
