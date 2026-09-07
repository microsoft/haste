# Feature: Common Prediction Results

**Status:** implemented
**Date:** 2026-09-06
**Priority:** P0
**Work items:** [#183](https://github.com/microsoft/haste/pull/183), [#136](https://github.com/microsoft/haste/pull/136)

Standard inference and interactive labeling share the existing View Results
page. Both produce the prediction-attribute sidecar when they create predictions,
not when an analyst opens results. Geometry comes from the layer-owned footprint
PMTiles introduced in #183.

## Scope

Keep this change to the attribute writer, two existing producer paths, protected
artifact reads, and the shared viewer. `Model` holds result pointers and output
identity. No shadow metadata store, raw-result lease framework, cancellation/
deletion redesign, new queue, first-open generation, or automatic backfill.
Versioned editing is the separate PR stacked on this one.

## Documents

[Design and compatibility](design.md), [acceptance criteria](user-stories.md),
and [implementation/validation plan](plan.md).
