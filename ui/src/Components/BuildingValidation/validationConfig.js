// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

// Rules for the Building Validation sample-size setting.
//
// The server is the authority — validation labels are layer-scoped and
// shared last-write-wins, so only it sees the real label set when two people
// are working at once. This mirrors its rules so the modal can answer
// immediately instead of round-tripping to learn that a change is refused.
// The outcome names match hastegeo.core.utils.validation_config so the two
// tables read the same way.

export const DEFAULT_VALIDATION_SAMPLE = 200;
export const MIN_VALIDATION_SAMPLE = 1;
// Matches the server-side clamp in GetBuildingFootprintsGeoJSON; a larger
// number would be silently reduced.
export const MAX_VALIDATION_SAMPLE = 2000;

export const OUTCOME_NOOP = "noop";
export const OUTCOME_EXTEND = "extend";
export const OUTCOME_RESAMPLE = "resample";
export const OUTCOME_BLOCKED = "blocked";
export const OUTCOME_INVALID = "invalid";

/**
 * Read the configured sample size out of a GetBuildingValidation response.
 *
 * A layer nobody has configured — and any document written before the
 * setting existed — resolves to the default, which is the count those layers
 * already used.
 *
 * @param {object|null|undefined} validation - GetBuildingValidation body.
 * @returns {number} The configured sample size.
 */
export function resolveSampleSize(validation) {
  const value = validation?.sampleSize;
  if (!Number.isInteger(value)) return DEFAULT_VALIDATION_SAMPLE;
  return Math.min(
    MAX_VALIDATION_SAMPLE,
    Math.max(MIN_VALIDATION_SAMPLE, value)
  );
}

/**
 * Decide whether a sample-size change may be applied.
 *
 * Growing is always safe: the sample is drawn as a prefix of a seeded
 * permutation, so a larger count keeps every building already in the set and
 * adds only the difference. Shrinking drops buildings off the end of that
 * prefix, which is fine while nothing is labeled and destroys work once
 * something is.
 *
 * @param {number} current - The layer's stored sample size.
 * @param {unknown} next - The requested size, straight from the input.
 * @param {number} labelCount - How many validation labels the layer holds.
 * @returns {{outcome: string, allowed: boolean, message: string}}
 */
export function canApplySampleSize(current, next, labelCount) {
  if (!Number.isInteger(next)) {
    return blocked(OUTCOME_INVALID, "Enter a whole number.");
  }

  if (next < MIN_VALIDATION_SAMPLE || next > MAX_VALIDATION_SAMPLE) {
    return blocked(
      OUTCOME_INVALID,
      `Enter a number between ${MIN_VALIDATION_SAMPLE} and ` +
        `${MAX_VALIDATION_SAMPLE}.`
    );
  }

  const from = Number.isInteger(current) ? current : DEFAULT_VALIDATION_SAMPLE;

  if (next === from) return allow(OUTCOME_NOOP);
  if (next > from) return allow(OUTCOME_EXTEND);
  if (!labelCount) return allow(OUTCOME_RESAMPLE);

  return blocked(
    OUTCOME_BLOCKED,
    `This layer has ${labelCount} validation label${
      labelCount === 1 ? "" : "s"
    }. Lowering the count from ${from} to ${next} would drop labeled ` +
      "buildings from the set. Clear the validation labels first."
  );
}

function allow(outcome) {
  return { outcome, allowed: true, message: "" };
}

function blocked(outcome, message) {
  return { outcome, allowed: false, message };
}
