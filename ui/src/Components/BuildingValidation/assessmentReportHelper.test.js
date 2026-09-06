// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { precisionRecallPresentation } from "./assessmentReportHelper.js";

test("edited precision/recall is one operating point and AP is unavailable", () => {
  assert.deepEqual(precisionRecallPresentation({
    predictionVersion: 3, metrics: { averagePrecision: null },
    precisionRecallCurve: { mode: "operating_point", precision: [0.8], recall: [0.6], thresholds: [] },
  }), { mode: "operating_point", precision: [0.8], recall: [0.6], averagePrecision: null });
});
test("edited classes cannot be plotted as a fabricated continuous curve", () => {
  const result = precisionRecallPresentation({
    predictionVersion: 3, metrics: { averagePrecision: 0.9 },
    precisionRecallCurve: { precision: [0.9, 0.8], recall: [0.2, 0.8] },
  });
  assert.deepEqual(result.precision, []);
  assert.equal(result.mode, "operating_point");
  assert.equal(result.averagePrecision, null);
});
test("raw report curves and average precision remain unchanged", () => {
  const curve = { precision: [1, 0.8], recall: [0.3, 1] };
  const result = precisionRecallPresentation({ predictionVersion: 0, precisionRecallCurve: curve, metrics: { averagePrecision: 0.6 } });
  assert.equal(result.precision, curve.precision);
  assert.equal(result.recall, curve.recall);
  assert.equal(result.averagePrecision, 0.6);
});
