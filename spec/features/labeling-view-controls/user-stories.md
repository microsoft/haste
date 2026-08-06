# User Stories: Labeling View Controls

## Contents

- [Stories](#stories)
- [Agent assignment](#agent-assignment)
- [Out of scope](#out-of-scope)
- [Traceability](#traceability)

## Stories

### US-001: Discover shortcuts in every labeling-related view

**As an** analyst, **I want** visible, consistent shortcut help, **so that** I
can work quickly without guessing controls.

```gherkin
Given I open Results, Interactive Labeler, Labeling Tool, or Building Validation
Then the view shows shortcut help that matches its implemented behavior
And letter shortcuts work in lowercase and uppercase
And shortcuts do not run while I type in an editable control
```

### US-002: Compare imagery consistently

**As an** analyst, **I want** consistent imagery keys, **so that** comparison
behavior transfers between views.

```gherkin
Given a view supports swipe comparison
When I press A, S, or D
Then the divider moves left, split, or right respectively
```

```gherkin
Given a view uses a single map
When I press A or D
Then pre-event/basemap or post-event imagery is shown respectively
And no split behavior is added
```

### US-003: Start Interactive Labeler in swipe mode

**As an** analyst, **I want** pre/post swipe available immediately, **so that**
I can compare imagery while assigning labels.

```gherkin
Given the Interactive Labeler finishes loading
Then Swipe (pre-event) is on by default
And pre imagery is on the left and post imagery is on the right
```

### US-004: Review model disagreements

**As an** analyst, **I want** to highlight model disagreements, **so that** I
can focus corrections on useful examples.

```gherkin
Given at least 3 valid labels exist in at least 2 classes
When I enable Show misclassified buildings under Advanced
Then the current model trains on demand or is reused
And only buildings with a human label whose prediction differs are emphasized
And the legend explains the mode
```

```gherkin
Given Misclassified mode is active
When Predicted or Uncertainty view is enabled
Then Misclassified mode turns off
When labels fall below the training threshold
Then Misclassified mode turns off and becomes disabled
```

## Agent Assignment

| Story | Implementing agent | Validating agent | UI path |
|---|---|---|---|
| US-001 | `ui` | `ui-validation` | shared shortcut component and four views |
| US-002 | `ui` | `ui-validation` | Visualizer, Interactive Labeler, Labeling Tool, Building Validation |
| US-003 | `ui` | `ui-validation` | `InteractiveLabeler/InteractiveLabeler.jsx` |
| US-004 | `ui` | `ui-validation` | `InteractiveLabeler/InteractiveLabeler.jsx` |

## Out of Scope

- API or persistence changes.
- A split view for single-map labeling or validation.
- A new model training implementation.

## Traceability

US-001 and US-002 implement
[#47](https://github.com/microsoft/haste/issues/47). US-004 implements
[#100](https://github.com/microsoft/haste/issues/100). US-003 implements
[#104](https://github.com/microsoft/haste/issues/104).
