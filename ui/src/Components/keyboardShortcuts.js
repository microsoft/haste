// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export const VISUALIZER_SHORTCUTS = [
  {
    keys: ["A", "S", "D"],
    description: "Move the swipe divider left / split / right",
  },
];

export const INTERACTIVE_LABELER_SHORTCUTS = [
  {
    keys: ["1", "2", "3"],
    description: "Set Intact / Damaged / Cloudy",
  },
  { keys: ["T"], description: "Cycle the selected class" },
  { keys: ["P"], description: "Toggle Labeled / Predicted view" },
  { keys: ["Space"], description: "Show / hide footprints" },
  {
    keys: ["Ctrl", "drag"],
    separator: " + ",
    description: "Box-label buildings",
  },
  {
    keys: ["A", "S", "D"],
    description: "With Swipe on: move the divider left / split / right",
  },
];

export const LABELING_TOOL_SHORTCUTS = [
  {
    keys: ["A", "D"],
    description: "Show pre (or basemap) / post imagery",
  },
];

export const BUILDING_VALIDATION_SHORTCUTS = [
  {
    keys: ["1", "2", "3"],
    description: "Label Damaged / Not Damaged / Unknown",
  },
  {
    keys: ["←", "→"],
    description: "Previous / next building",
  },
  {
    keys: ["A", "D"],
    description: "Show pre (or basemap) / post imagery",
  },
];

export function shouldIgnoreShortcut(event) {
  const target = event?.target;
  const tagName = target?.tagName?.toUpperCase();
  return (
    ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(tagName) ||
    target?.isContentEditable === true ||
    target?.closest?.(
      "button, a, [role='button'], [role='link'], [role='switch']"
    ) != null
  );
}
