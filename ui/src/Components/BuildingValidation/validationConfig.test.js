// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_VALIDATION_SAMPLE,
  MAX_VALIDATION_SAMPLE,
  MIN_VALIDATION_SAMPLE,
  OUTCOME_BLOCKED,
  OUTCOME_EXTEND,
  OUTCOME_INVALID,
  OUTCOME_NOOP,
  OUTCOME_RESAMPLE,
  canApplySampleSize,
  resolveSampleSize,
} from "./validationConfig.js";

// ── resolveSampleSize ───────────────────────────────────────────────────────

test("a layer with no validation document uses the default", () => {
  assert.equal(resolveSampleSize(undefined), DEFAULT_VALIDATION_SAMPLE);
  assert.equal(resolveSampleSize(null), DEFAULT_VALIDATION_SAMPLE);
  assert.equal(resolveSampleSize({}), DEFAULT_VALIDATION_SAMPLE);
});

test("a document written before the setting existed reads as the default", () => {
  // No migration: these keep the count they already had.
  assert.equal(
    resolveSampleSize({ imageLayerId: "layer", labels: {} }),
    DEFAULT_VALIDATION_SAMPLE
  );
});

test("a configured value is read back", () => {
  assert.equal(resolveSampleSize({ sampleSize: 500 }), 500);
});

test("a stored value outside the range is clamped", () => {
  assert.equal(resolveSampleSize({ sampleSize: 99999 }), MAX_VALIDATION_SAMPLE);
  assert.equal(resolveSampleSize({ sampleSize: 0 }), MIN_VALIDATION_SAMPLE);
});

test("a non-integer stored value falls back to the default", () => {
  for (const bad of ["300", 12.5, true, null]) {
    assert.equal(
      resolveSampleSize({ sampleSize: bad }),
      DEFAULT_VALIDATION_SAMPLE
    );
  }
});

// ── canApplySampleSize ──────────────────────────────────────────────────────

test("the same value is a no-op", () => {
  const result = canApplySampleSize(200, 200, 40);

  assert.equal(result.outcome, OUTCOME_NOOP);
  assert.equal(result.allowed, true);
});

test("growing is allowed even when labels exist", () => {
  // The point of the feature: asking for more never destroys work, because
  // the draw is a permutation prefix.
  const result = canApplySampleSize(200, 300, 40);

  assert.equal(result.outcome, OUTCOME_EXTEND);
  assert.equal(result.allowed, true);
});

test("growing is allowed with no labels", () => {
  assert.equal(canApplySampleSize(200, 300, 0).outcome, OUTCOME_EXTEND);
});

test("shrinking is allowed when nothing is labeled", () => {
  const result = canApplySampleSize(300, 100, 0);

  assert.equal(result.outcome, OUTCOME_RESAMPLE);
  assert.equal(result.allowed, true);
});

test("shrinking is blocked once anything is labeled", () => {
  const result = canApplySampleSize(300, 100, 40);

  assert.equal(result.outcome, OUTCOME_BLOCKED);
  assert.equal(result.allowed, false);
});

test("one label is enough to block shrinking", () => {
  assert.equal(canApplySampleSize(300, 299, 1).outcome, OUTCOME_BLOCKED);
});

test("the block message says what is at stake and what to do", () => {
  const result = canApplySampleSize(300, 100, 40);

  assert.match(result.message, /40 validation labels/);
  assert.match(result.message, /from 300 to 100/);
  assert.match(result.message, /Clear the validation labels first/);
});

test("the block message stays grammatical for a single label", () => {
  const result = canApplySampleSize(300, 100, 1);

  assert.match(result.message, /1 validation label\./);
});

test("values outside the supported range are rejected", () => {
  for (const bad of [0, -1, MAX_VALIDATION_SAMPLE + 1]) {
    const result = canApplySampleSize(200, bad, 0);
    assert.equal(result.outcome, OUTCOME_INVALID);
    assert.equal(result.allowed, false);
  }
});

test("the range boundaries are accepted", () => {
  assert.equal(
    canApplySampleSize(200, MIN_VALIDATION_SAMPLE, 0).outcome,
    OUTCOME_RESAMPLE
  );
  assert.equal(
    canApplySampleSize(200, MAX_VALIDATION_SAMPLE, 0).outcome,
    OUTCOME_EXTEND
  );
});

test("non-integers are rejected rather than coerced", () => {
  // A half-typed input must not be treated as a valid count.
  for (const bad of ["300", 12.5, NaN, null, undefined]) {
    assert.equal(canApplySampleSize(200, bad, 0).outcome, OUTCOME_INVALID);
  }
});

test("a missing current value is treated as the default", () => {
  // Opening the modal on a never-configured layer compares against 200.
  assert.equal(canApplySampleSize(undefined, 300, 0).outcome, OUTCOME_EXTEND);
  assert.equal(canApplySampleSize(undefined, 100, 5).outcome, OUTCOME_BLOCKED);
});
