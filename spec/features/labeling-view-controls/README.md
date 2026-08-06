# Feature: Labeling View Controls

**Status:** implemented
**Date:** 2026-08-05
**Priority:** P1
**Work items:** [#47](https://github.com/microsoft/haste/issues/47),
[#100](https://github.com/microsoft/haste/issues/100),
[#104](https://github.com/microsoft/haste/issues/104)

## Contents

- [Summary](#summary)
- [Success criteria](#success-criteria)
- [Scope](#scope)
- [Documents](#documents)
- [Issue note](#issue-note)

## Summary

Standardize visible keyboard shortcut help and imagery-comparison keys across
Results, Interactive Labeler, Labeling Tool, and Building Validation. Enable
the Interactive Labeler swipe map by default and add an Advanced mode that
highlights human labels that disagree with the current in-browser model.

## Success Criteria

- [x] All four views use shared, visible shortcut definitions.
- [x] Shortcuts ignore typing targets and accept lowercase or uppercase letters.
- [x] Imagery comparison uses `A` for pre/left, `S` for split where available,
  and `D` for post/right.
- [x] Interactive swipe starts enabled.
- [x] Misclassified mode highlights only labeled prediction mismatches and is
  mutually exclusive with Predicted and Uncertainty views.
- [x] Misclassified mode disables and turns off below the training threshold.

## Scope

The implementation is UI-only. It reuses Azure Maps, the existing in-browser
model, cached labels/predictions, and feature-state paint expressions. It adds
no API contract or dependency.

## Documents

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | UI and map-expression design | implemented |
| [user-stories.md](user-stories.md) | Acceptance criteria and ownership | implemented |
| [plan.md](plan.md) | Phased execution status | implemented |
| [test-plan.md](test-plan.md) | Validation scenarios | ready for validation |

## Issue Note

Issue [#104](https://github.com/microsoft/haste/issues/104) tracks enabling
swipe comparison by default in the Interactive Labeler.
