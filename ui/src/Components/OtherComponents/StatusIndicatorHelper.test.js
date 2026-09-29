import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { statusPresentation } from "./StatusIndicatorHelper.js";

const styles = readFileSync(new URL("../../assets/css/style.css", import.meta.url), "utf8");

function cssColor(selector, property) {
  const block = styles.match(new RegExp(`\\.${selector}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
  return block.match(new RegExp(`(?:^|[;\\s])${property}:\\s*(#[0-9a-fA-F]{6})`))?.[1];
}

function contrast(first, second) {
  const luminance = hex => {
    const [red, green, blue] = [1, 3, 5].map(index => {
      const channel = parseInt(hex.slice(index, index + 2), 16) / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
  };
  const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

test("queued jobs remain visible without messages or counters", () => {
  assert.deepEqual(statusPresentation({ status: "Queued" }), {
    label: "Queued", tone: "Queued", active: true, indeterminate: true, progress: null, stepText: "",
  });
});

test("missing initial telemetry is indeterminate, not invented zero progress", () => {
  assert.equal(statusPresentation({
    status: "InProgress", currentStep: 0, totalSteps: 2, progressPct: 0,
  }).indeterminate, true);
});

test("valid shared backend counters are rendered", () => {
  assert.deepEqual(statusPresentation({
    status: "InProgress", currentStep: 1, totalSteps: 4, progressPct: 25,
  }), {
    label: "InProgress", tone: "InProgress", active: true, indeterminate: false, progress: 25, stepText: "1/4",
  });
});

test("terminal states do not depend on metrics or log messages", () => {
  for (const status of ["Processed", "Failed", "Cancelled"]) {
    const view = statusPresentation({ status, progressPct: 0 });
    assert.equal(view.label, status);
    assert.equal(view.active, false);
    assert.equal(view.indeterminate, false);
  }
});

test("every terminal badge keeps readable text, including unknown statuses", () => {
  const text = cssColor("modelStatus", "color");
  assert.ok(text, "badge text color is not defined");
  for (const status of ["Processed", "Completed", "Failed", "Cancelled", undefined, "", "Preparing", "In Progress"]) {
    const view = statusPresentation({ status });
    assert.equal(view.active, false);
    const background = cssColor(`modelStatus-${view.tone}`, "background-color");
    assert.ok(background, `"${view.label}" badge has no background color`);
    assert.ok(
      contrast(text, background) >= 4.5,
      `"${view.label}" badge contrast is ${contrast(text, background).toFixed(2)}:1`,
    );
  }
  assert.equal(statusPresentation({ status: "Preparing" }).label, "Preparing");
});

test("unknown and malformed progress stays unavailable", () => {
  for (const progressPct of [undefined, null, Number.NaN, Infinity, "50"]) {
    const view = statusPresentation({
      status: "InProgress", currentStep: 1, totalSteps: 2, progressPct,
    });
    assert.equal(view.indeterminate, true);
    assert.equal(view.progress, null);
  }
  assert.equal(statusPresentation({}).label, "Unknown");
});

test("progress is bounded without changing the underlying state", () => {
  assert.equal(statusPresentation({
    status: "InProgress", currentStep: 5, totalSteps: 4, progressPct: 125,
  }).progress, 100);
});

test("recorded percentage is not hidden when legacy step counters are missing", () => {
  const view = statusPresentation({ status: "InProgress", progressPct: 25 });
  assert.equal(view.progress, 25);
  assert.equal(view.indeterminate, false);
  assert.equal(view.stepText, "");
});
