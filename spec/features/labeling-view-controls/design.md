# Design: Labeling View Controls

## Contents

- [Overview](#overview)
- [Shared shortcuts](#shared-shortcuts)
- [Imagery behavior](#imagery-behavior)
- [Misclassified mode](#misclassified-mode)
- [State updates](#state-updates)
- [Accessibility](#accessibility)

## Overview

The change stays within `ui/src/Components/`. A shared shortcut data module
defines the labels shown in each view and a shared Fluent UI component renders
them. Each existing view retains its own map and domain behavior.

## Shared Shortcuts

`keyboardShortcuts.js` exports view-specific shortcut arrays and the common
typing-target guard. `KeyboardShortcutHelp.jsx` renders those arrays with
semantic keyboard labels.

| View | Shortcuts |
|---|---|
| Results / Visualizer | `A`, `S`, `D` |
| Interactive Labeler | `1/2/3`, `T`, `P`, `Space`, `Ctrl+drag`, `A/S/D` |
| Labeling Tool | `A`, `D` |
| Building Validation | `1/2/3`, arrows, `A`, `D` |

## Imagery Behavior

Swipe views retain divider positions: `A` moves left, `S` centers, and `D`
moves right. Single-map views use `A` to reveal pre-event imagery (or the
basemap fallback) and `D` to reveal post-event imagery. They do not implement
an unsupported split state.

## Misclassified Mode

The Advanced toggle is enabled when at least three valid labels exist in each
of two classes, matching the existing `canTrain` condition. Enabling the mode
trains or reuses the existing on-demand model and predicts the viewport.

The fill expression requires both a valid human `label` feature-state and a
valid `pred` feature-state, then checks that they differ. Mismatches receive a
distinct orange fill. Correctly classified and unlabeled buildings remain
transparent and are not represented as misclassified.

Predicted, Uncertainty, and Misclassified modes are mutually exclusive. The
misclassified toggle turns off automatically if labels fall below the
training threshold.

## State Updates

The mode reuses `labeledMapRef`, `predictionsMapRef`, `trainedModelRef`, and
the existing `maybeTrainAndPredict` path. Viewport hydration reapplies label
and prediction state before evaluating the expression. Label additions,
box-labeling, removals, retraining, full prediction, and clearing all trigger
the same hydration or feature-state reset paths.

## Accessibility

Letter comparisons normalize `event.key` to lowercase, so uppercase and
lowercase work. Global handlers return for editable controls, buttons, links,
and Fluent UI switch controls so they do not override typing, activation, or
browser shortcuts. Visible help uses `kbd`, `dt`, and `dd` semantics.
