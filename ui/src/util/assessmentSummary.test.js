// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { buildAssessmentSummary } from "./assessmentSummary.js";

const report = {
  predictions: {
    total: 1496, knownNonCloudy: 1430, cloudy: 29, unscored: 37,
    predictedDamaged: 791, predictedDamagedPctOfKnown: 55.31,
  },
  matched: 0, metrics: null,
};

test("catalog summary distinguishes cloud/unknown coverage from unscored observations", () => {
  const summary = buildAssessmentSummary(report);
  assert.match(summary, /1,496 building footprints in the results/);
  assert.match(summary, /29 were excluded because of cloud or unknown coverage/);
  assert.match(summary, /37 had no observation \(outside coverage or NoData\) and were excluded/);
  assert.match(summary, /Among the 1,430 non-cloudy footprints with observations/);
  assert.match(summary, /791 \(55.31%\) were damaged/);
  assert.doesNotMatch(summary, /obscured by clouds|remaining|precision|recall/);
});

test("absent, null, and zero unscored preserve the same sensible legacy summary", () => {
  const predictions = { total: 1459, knownNonCloudy: 1430, cloudy: 29, predictedDamaged: 791, predictedDamagedPctOfKnown: 55.31 };
  const absent = buildAssessmentSummary({ predictions });
  assert.equal(buildAssessmentSummary({ predictions: { ...predictions, unscored: 0 } }), absent);
  assert.equal(buildAssessmentSummary({ predictions: { ...predictions, unscored: null } }), absent);
  assert.doesNotMatch(absent, /NoData|had no observation/);
  assert.match(absent, /cloud or unknown coverage/);
});

test("no labels or null metrics do not fabricate accuracy claims", () => {
  const summary = buildAssessmentSummary(report);
  assert.match(summary, /No human validation labels are available/);
  assert.doesNotMatch(summary, /Estimated recall|precision [0-9]|accuracy [0-9]/);
});

test("unmatched labels are not described as absent labels", () => {
  const summary = buildAssessmentSummary({ ...report, totalLabels: 8, sureLabels: 8 });
  assert.match(summary, /No human validation labels could be matched to scored predictions/);
  assert.doesNotMatch(summary, /No human validation labels are available|Estimated recall/);
});

test("empty results do not invent damage percentages or validation metrics", () => {
  const summary = buildAssessmentSummary({
    predictions: { total: 0, knownNonCloudy: 0, cloudy: 0, unscored: 0, predictedDamaged: 0 },
  });
  assert.match(summary, /no building footprints in the results/);
  assert.doesNotMatch(summary, /%|were damaged|Estimated recall/);
});

test("all-unscored results retain the total without implying confident non-damage", () => {
  const summary = buildAssessmentSummary({
    predictions: { total: 37, knownNonCloudy: 0, cloudy: 0, unscored: 37, predictedDamaged: 0 },
    matched: 0, metrics: null,
  });
  assert.match(summary, /37 building footprints/);
  assert.match(summary, /37 had no observation/);
  assert.match(summary, /No scored, non-cloudy observations are available/);
  assert.doesNotMatch(summary, /%|were damaged|not damaged|Estimated recall/);
});

test("all cloud/unknown coverage does not report a damage rate", () => {
  const summary = buildAssessmentSummary({
    predictions: { total: 29, knownNonCloudy: 0, cloudy: 29, predictedDamaged: 0 },
  });
  assert.match(summary, /29 were excluded because of cloud or unknown coverage/);
  assert.match(summary, /no damage rate or validation metrics can be reported/);
  assert.doesNotMatch(summary, /%|had no observation/);
});

test("zero exclusions and zero predicted damage remain valid scored observations", () => {
  const summary = buildAssessmentSummary({
    predictions: { total: 20, knownNonCloudy: 20, cloudy: 0, unscored: 0, predictedDamaged: 0, predictedDamagedPctOfKnown: 0 },
  });
  assert.match(summary, /Among the 20 non-cloudy footprints with observations/);
  assert.match(summary, /0 \(0%\) were damaged/);
});

test("matched-label metrics and population estimates keep their existing values", () => {
  const summary = buildAssessmentSummary({
    ...report, matched: 10, totalLabels: 12, sureLabels: 10,
    metrics: { recall: 0.8, precision: 0.75 },
    populationEstimate: {
      N: 100, minAreaM2: 10, estimatedDamaged: 40, pHat: 0.4, ciLower: 30, ciUpper: 50,
    },
  });
  assert.match(summary, /We independently labeled 12 footprints; 10 were sure-labeled/);
  assert.match(summary, /Estimated recall 80.0% and precision 75.0%/);
  assert.match(summary, /40 damaged buildings \(40.0%\) with a 95% CI of \[30, 50\]/);
});

test("missing report data returns no summary and inputs remain unchanged", () => {
  for (const input of [undefined, null, {}, { predictions: null }]) {
    assert.equal(buildAssessmentSummary(input), "");
  }
  const frozen = Object.freeze({ ...report, predictions: Object.freeze({ ...report.predictions }) });
  assert.equal(buildAssessmentSummary(frozen), buildAssessmentSummary(report));
});
