# Plan: Labeling View Controls

## Contents

- [Phase 1: Specification](#phase-1-specification)
- [Phase 2: Shared controls](#phase-2-shared-controls)
- [Phase 3: View integration](#phase-3-view-integration)
- [Phase 4: Validation](#phase-4-validation)

## Phase 1: Specification

| Task | Agent | Story | Status |
|---|---|---|---|
| Define shortcut, swipe-default, and disagreement behavior | `ui` | US-001–004 | done |
| Define UI validation coverage | `ui` | US-001–004 | done |

## Phase 2: Shared Controls

| Task | Agent | Story | Status |
|---|---|---|---|
| Add shared shortcut definitions and typing guard | `ui` | US-001/002 | done |
| Add shared Fluent UI shortcut-help component | `ui` | US-001 | done |

## Phase 3: View Integration

| Task | Agent | Story | Status |
|---|---|---|---|
| Results / Visualizer shortcut help and guarded handler | `ui` | US-001/002 | done |
| Interactive shortcuts and default swipe | `ui` | US-001–003 | done |
| Labeling Tool `A`/`D` imagery controls | `ui` | US-001/002 | done |
| Building Validation imagery keys and help | `ui` | US-001/002 | done |
| Advanced misclassified mode | `ui` | US-004 | done |
| Update in-app and usage help | `ui` | US-001/002 | done |

## Phase 4: Validation

| Task | Agent | Story | Status |
|---|---|---|---|
| Run UI lint | `ui` | US-001–004 | blocked — ESLint 9 does not load the repository `.eslintrc.cjs` |
| Run production build | `ui` | US-001–004 | done |
| Execute browser scenarios in test plan | `ui-validation` | US-001–004 | pending |
