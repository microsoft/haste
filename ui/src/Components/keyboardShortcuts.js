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
    keys: ["Ctrl", "right-drag"],
    separator: " + ",
    description: "Box-clear labels",
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

// Prediction Editor (edit a model's predictions and save a new version).
export const PREDICTION_EDITOR_SHORTCUTS = [
  {
    keys: ["1", "2", "3"],
    description:
      "Set the selected building to Damaged / Not Damaged / Unknown",
  },
  {
    keys: ["←", "→"],
    description: "Previous / next building in the current filter",
  },
  {
    keys: ["Click"],
    description: "Apply the current click action to a footprint",
  },
  {
    keys: ["Ctrl", "drag"],
    separator: " + ",
    description: "Box-select footprints and edit them together",
  },
  {
    keys: ["Right-click"],
    description: "Undo an edit — back to the model's class",
  },
  {
    // Direction matters: the comparison map (pre-event imagery, or the
    // basemap) is the swipe PRIMARY and sits LEFT of the divider, so moving
    // the divider left uncovers MORE of the post-event map and moving it
    // right uncovers more of the comparison map.
    keys: ["A", "S", "D"],
    description:
      "With Swipe on: snap the divider left / centre / right — left uncovers more post-event imagery, right more of the pre-event (or basemap) pane",
  },
];

// Input types that are not free-text entry. Focus can legitimately sit on
// one of these while the user keeps driving the page from the keyboard.
const NON_TEXT_INPUT_TYPES = new Set([
  "button",
  "checkbox",
  "color",
  "file",
  "image",
  "radio",
  "range",
  "reset",
  "submit",
]);

// Controls that act on Space / Enter. Firing a shortcut for those keys as
// well would double-act (Space would click the focused button *and*
// toggle footprints).
const ACTIVATABLE_SELECTOR = [
  "button",
  "a[href]",
  "[role='button']",
  "[role='link']",
  "[role='switch']",
  "[role='checkbox']",
  "[role='tab']",
  "[role='menuitem']",
  "[role='option']",
].join(", ");

// Controls that move their own selection with the arrow keys.
const ARROW_CONSUMER_SELECTOR = [
  "input[type='radio']",
  "input[type='range']",
  "[role='listbox']",
  "[role='combobox']",
  "[role='menu']",
  "[role='radiogroup']",
  "[role='slider']",
  "[role='spinbutton']",
  "[role='tablist']",
].join(", ");

const ACTIVATION_KEYS = new Set([" ", "Spacebar", "Enter"]);
const ARROW_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
]);

// True when the target swallows ordinary character keys: real typing
// surfaces, plus <select>, which does letter type-ahead.
function isTextEntryTarget(target) {
  if (target?.isContentEditable === true) return true;
  const tagName = target?.tagName?.toUpperCase();
  if (tagName === "TEXTAREA" || tagName === "SELECT") return true;
  if (tagName === "INPUT") {
    const type = (target.type || "text").toLowerCase();
    return !NON_TEXT_INPUT_TYPES.has(type);
  }
  return false;
}

// Shortcuts are suppressed only for keys the focused element genuinely
// handles itself. Anything broader breaks the common case where a click
// leaves focus parked on a button, switch, or nav link — after which
// every shortcut on the page would silently stop responding.
export function shouldIgnoreShortcut(event) {
  const target = event?.target;
  if (isTextEntryTarget(target)) return true;

  const key = event?.key;
  if (ACTIVATION_KEYS.has(key)) {
    return target?.closest?.(ACTIVATABLE_SELECTOR) != null;
  }
  if (ARROW_KEYS.has(key)) {
    return target?.closest?.(ARROW_CONSUMER_SELECTOR) != null;
  }
  return false;
}
