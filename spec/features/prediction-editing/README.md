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
- Colored class selection and click/Ctrl-drag painting provide direct editing.
  A Review filter, Previous/Next buttons, position indicator, arrow navigation,
  and 1/2/3 labeling support rapid review without a detailed inspector or separate
  apply controls.
- Raw and saved standard-model results support a damage slider that preserves
  manual assignments; interactive models use discrete class choices.
- Saving writes a versioned GeoPackage and matching sidecar without replacing
  raw predictions or an existing saved version. Unchanged drafts cannot be saved
  from the UI, and editing uses visualizer readiness rather than a separate session.
- Map selection, download selection, and post-save selection agree.
- Reports default to the latest saved version and allow explicit raw/older
  selections; assessment respects the analyst's class overrides.

## Components

Backend models/processors/API, prediction attribute utilities, Visualizer,
model-result download controls, Validation/Assessment modals, and keyboard help.
There is no additional Azure queue, service, or automatic first-open backfill.
History stays on `Model`; only a small editor-save lock and per-version replay
fingerprint are added. The discarded raw-result metadata framework is not
relocated here.

## Documents

[Design](design.md), [stories](user-stories.md), [plan](plan.md),
[data model](data-model.md), [tests](test-plan.md),
[impact](impact-analysis.md), [rollout](rollout.md).
