// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { buildAssessmentSummary } from "./assessmentSummary.js";

const report = {
  predictions: {
    total: 1496, knownNonCloudy: 1430, cloudy: 66, unscored: 37,
    predictedDamaged: 791, predictedDamagedPctOfKnown: 55.31,
  },
  matched: 0, metrics: null,
};

test("catalog summary explains unscored observations as a subset of Unknown, not additional exclusions", () => {
  const summary = buildAssessmentSummary(report);
  assert.match(summary, /1,496 building footprints in the results/);
  assert.match(summary, /66 had Unknown or cloud-covered predictions and were excluded/);
  assert.match(summary, /Of these Unknown predictions, 37 had no raw observation \(outside coverage or NoData\); they are already included in the excluded total/);
  assert.match(summary, /Among the 1,430 known footprints/);
  assert.match(summary, /791 \(55.31%\) were damaged/);
  assert.doesNotMatch(summary, /obscured by clouds|remaining|precision|recall/);
  assert.equal(report.predictions.total, report.predictions.knownNonCloudy + report.predictions.cloudy);
  assert.equal((summary.match(/were excluded/g) || []).length, 1);
});

test("absent, null, and zero unscored preserve the same sensible legacy summary", () => {
  const predictions = { total: 1459, knownNonCloudy: 1430, cloudy: 29, predictedDamaged: 791, predictedDamagedPctOfKnown: 55.31 };
  const absent = buildAssessmentSummary({ predictions });
  assert.equal(buildAssessmentSummary({ predictions: { ...predictions, unscored: 0 } }), absent);
  assert.equal(buildAssessmentSummary({ predictions: { ...predictions, unscored: null } }), absent);
  assert.doesNotMatch(absent, /NoData|had no raw observation/);
  assert.match(absent, /Unknown or cloud-covered predictions/);
});

test("no labels or null metrics do not fabricate accuracy claims", () => {
  const summary = buildAssessmentSummary(report);
  assert.match(summary, /No human validation labels are available/);
  assert.doesNotMatch(summary, /Estimated recall|precision [0-9]|accuracy [0-9]/);
});

test("unmatched labels are not described as absent labels", () => {
  const summary = buildAssessmentSummary({ ...report, totalLabels: 8, sureLabels: 8 });
  assert.match(summary, /No human validation labels could be matched to known predictions/);
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
    predictions: { total: 37, knownNonCloudy: 0, cloudy: 37, unscored: 37, predictedDamaged: 0 },
    matched: 0, metrics: null,
  });
  assert.match(summary, /37 building footprints/);
  assert.match(summary, /37 had Unknown or cloud-covered predictions and were excluded/);
  assert.match(summary, /Of these Unknown predictions, 37 had no raw observation/);
  assert.match(summary, /No known predictions are available/);
  assert.doesNotMatch(summary, /%|were damaged|not damaged|Estimated recall/);
});

test("all cloud/unknown coverage does not report a damage rate", () => {
  const summary = buildAssessmentSummary({
    predictions: { total: 29, knownNonCloudy: 0, cloudy: 29, predictedDamaged: 0 },
  });
  assert.match(summary, /29 had Unknown or cloud-covered predictions and were excluded/);
  assert.match(summary, /no damage rate or validation metrics can be reported/);
  assert.doesNotMatch(summary, /%|had no raw observation/);
});

test("zero exclusions and zero predicted damage remain valid scored observations", () => {
  const summary = buildAssessmentSummary({
    predictions: { total: 20, knownNonCloudy: 20, cloudy: 0, unscored: 0, predictedDamaged: 0, predictedDamagedPctOfKnown: 0 },
  });
  assert.match(summary, /Among the 20 known footprints/);
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

test("edited reports attribute damage to the exact saved version, not raw model predictions", () => {
  const summary = buildAssessmentSummary({ ...report, predictionVersion: 4 });
  assert.match(summary, /saved analyst classes in version 4 identify 791 \(55.31%\) as damaged/);
  assert.match(summary, /66 had Unknown or cloud-covered predictions and were excluded/);
  assert.match(summary, /Of these Unknown predictions, 37 had no raw observation/);
  assert.doesNotMatch(summary, /model predicted/);
  assert.match(buildAssessmentSummary({ ...report, predictionVersion: 0 }), /model predicted/);
});

test("empty and all-unscored saved versions never fabricate a damage rate", () => {
  for (const total of [0, 37]) {
    const summary = buildAssessmentSummary({
      predictionVersion: 2,
      predictions: { total, cloudy: total, unscored: total, knownNonCloudy: 0, predictedDamaged: 0 },
    });
    assert.match(summary, /no damage rate or validation metrics can be reported/);
    assert.doesNotMatch(summary, /%|as damaged|model predicted/);
  }
});

test("known saved analyst classes do not imply the presence of raw observations", () => {
  const summary = buildAssessmentSummary({
    predictionVersion: 2, matched: 2, totalLabels: 2, sureLabels: 2,
    predictions: {
      total: 3, knownNonCloudy: 2, cloudy: 1, unscored: 1,
      predictedDamaged: 1, predictedDamagedPctOfKnown: 50,
    },
    metrics: { precision: 1, recall: 1 },
  });
  assert.match(summary, /Of these Unknown predictions, 1 had no raw observation/);
  assert.match(summary, /Among the 2 known footprints, the saved analyst classes in version 2 identify 1 \(50%\) as damaged/);
  assert.doesNotMatch(summary, /footprints with observations|model predicted/);
});

test("labels on Unknown predictions are not described as missing prediction rows", () => {
  const summary = buildAssessmentSummary({
    ...report, totalLabels: 8, sureLabels: 8, labeledUnknownPredictions: 8,
    labeledMissingFromPredictions: 0,
  });
  assert.match(summary, /No human validation labels could be matched to known predictions/);
  assert.doesNotMatch(summary, /missing predictions|missing prediction rows|No human validation labels are available/);
});
