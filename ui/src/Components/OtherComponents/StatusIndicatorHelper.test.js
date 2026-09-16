import test from "node:test";
import assert from "node:assert/strict";
import { statusPresentation } from "./StatusIndicatorHelper.js";

test("queued jobs remain visible without messages or counters", () => {
  assert.deepEqual(statusPresentation({ status: "Queued" }), {
    label: "Queued", active: true, indeterminate: true, progress: null, stepText: "",
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
    label: "InProgress", active: true, indeterminate: false, progress: 25, stepText: "1/4",
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
