# Feature: Versioned Prediction Editing

**Contents:** [Summary](#summary) - [Success criteria](#success-criteria) -
[Components](#components) - [Documents](#documents)

**Status:** implemented
**Date:** 2026-09-06
**Priority:** P0
**Design reference:** [#136](https://github.com/microsoft/haste/pull/136)

## Summary

Adapt #136's editing experience into the shared View Results page. Analysts
correct footprint classes, save immutable numbered results, and select which
version they view, download, or report on. This is stacked on
[common prediction results](../common-prediction-results/README.md), not a
standalone editor or a new preparation pipeline.

## Success Criteria

- The pencil or E opens the editor on the existing swipe map.
- Class selection, click/box painting, reset, keyboard review, and standard-only
  threshold sliders match #136.
- Saving writes a versioned GeoPackage and matching sidecar without replacing
  raw predictions or an existing saved version.
- Map selection, download selection, and post-save selection agree.
- Reports default to the latest saved version and allow explicit raw/older
  selections; assessment respects the analyst's class overrides.

## Components

Backend models/processors/API, prediction attribute utilities, Visualizer,
model-result download controls, Validation/Assessment modals, and keyboard help.
There is no additional Azure queue, service, or automatic first-open backfill.

## Documents

[Design](design.md), [stories](user-stories.md), [plan](plan.md),
[data model](data-model.md), [tests](test-plan.md),
[impact](impact-analysis.md), [rollout](rollout.md).
