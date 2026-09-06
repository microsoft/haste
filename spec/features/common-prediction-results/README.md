# Feature: Common Prediction Results

**Contents:** [Summary](#summary) - [Scope](#scope) -
[Success criteria](#success-criteria) - [Components](#components) -
[Documents](#documents)

**Status:** implemented
**Date:** 2026-09-06
**Priority:** P0
**Work items:** [#183](https://github.com/microsoft/haste/pull/183), [#136](https://github.com/microsoft/haste/pull/136)

## Summary

Standard inference and interactive labeling share the existing View Results
page. Both produce the prediction-attribute sidecar when they create predictions,
not when an analyst opens results. Geometry comes from the layer-owned footprint
PMTiles introduced in #183.

## Scope

This is the middle change in a three-PR stack: footprint review fixes, common
read-only results, then versioned prediction editing. Retain #136's vector-first
swipe-map design without its prediction-preparation queue or first-open work.
No additional queue, polling-based sidecar preparation, or automatic historical
backfill is introduced.

## Success Criteria

- Interactive prediction saves and standard inference produce matching sidecars.
- Both workflows expose View Results with consistent footprint classes.
- Opening results only reads artifacts; missing artifacts have explicit guidance.
- Empty interactive predictions do not enable results or publishing.
- Existing project data and the running development stack are not migrated.

## Components

| Component | Responsibility |
|---|---|
| `hastelib` | Prediction artifacts, readiness, visualizer payload |
| `api/hastefuncapi` | Thin prediction-save and artifact/read wrappers |
| `docker/training/code` | Eager sidecars during inference |
| `ui` | Shared read-only results and PMTiles protocol |

## Documents

[Design](design.md), [stories](user-stories.md), [plan](plan.md),
[data model](data-model.md), [tests](test-plan.md),
[impact](impact-analysis.md), [rollout](rollout.md).
