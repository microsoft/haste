# Test Plan: Labeling View Controls

## Contents

- [Strategy](#strategy)
- [Shortcut scenarios](#shortcut-scenarios)
- [Misclassified scenarios](#misclassified-scenarios)
- [Regression scenarios](#regression-scenarios)
- [Sign-off](#sign-off)

## Strategy

The `ui` agent validates static quality with ESLint and a production Vite
build. The `ui-validation` agent validates user behavior in a browser with
Playwright, using mocked app/API data where practical.

## Shortcut Scenarios

| ID | View | Scenario | Expected |
|---|---|---|---|
| UI-001 | Results | Press `A`, `S`, `D` | Divider moves left, center, right |
| UI-002 | Interactive | Press `1/2/3`, `T`, `P`, `Space` | Documented action runs |
| UI-003 | Interactive | Use `Ctrl+drag`, then `A/S/D` | Box label and swipe actions run |
| UI-004 | Labeling Tool | Press `A`, `D` | Pre/post selection works |
| UI-005 | Validation | Press `1/2/3`, arrows, `A/D` | Label, navigation, and imagery actions work |
| UI-006 | All | Repeat letter keys with Shift/Caps Lock | Same action runs |
| UI-007 | All | Use shortcut keys in editable or interactive controls | No global shortcut overrides the control |
| UI-008 | All | Inspect visible shortcut help | Text matches behavior |

## Misclassified Scenarios

| ID | Scenario | Expected |
|---|---|---|
| UI-009 | Fewer than 3 labels in 2 classes | Toggle disabled with training-threshold copy |
| UI-010 | Enable at threshold | Model trains on demand; mismatch legend appears |
| UI-011 | Labeled prediction differs | Building receives misclassified emphasis |
| UI-012 | Labeled prediction matches | Building has no misclassified fill |
| UI-013 | Building has prediction but no human label | Building has no misclassified fill |
| UI-014 | Change a label or pan to new tiles | Prediction/mismatch display refreshes |
| UI-015 | Retrain or run full prediction | Current prediction state drives mismatch display |
| UI-016 | Enable Predicted or Uncertainty | Misclassified turns off |
| UI-017 | Clear labels or fall below threshold | Misclassified turns off and disables |

## Regression Scenarios

| ID | Scenario | Expected |
|---|---|---|
| REG-001 | Open Interactive Labeler | Swipe starts on with pre-left/post-right labels |
| REG-002 | Disable and re-enable swipe | Labeling interactions and map camera still work |
| REG-003 | Hide/show footprints | Labels and predictions remain cached |
| REG-004 | Save and restore labels | Hydration restores labels and mismatch evaluation |

## Sign-off

- [ ] `cd ui && npm run lint` (blocked: ESLint 9 requires an
  `eslint.config.*`; this repository currently provides `.eslintrc.cjs`)
- [x] `cd ui && npm run build`
- [ ] `ui-validation` Playwright scenarios pass.
