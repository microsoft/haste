import test from "node:test";
import assert from "node:assert/strict";

import {
  sourceTypeOptions,
  normalizeSourceTypeKey,
} from "./sourceTypeOptions.js";

test("lists only the supported visible imagery source types", () => {
  const visibleSourceKeys = sourceTypeOptions
    .filter((option) => option.showInDropdown)
    .map((option) => option.key);

  assert.deepEqual(visibleSourceKeys, [
    "n/a",
    "rgb/no_processing",
    "vantor",
    "planet_scope",
    "planet_skysat",
  ]);
});

test("keeps RGB no-processing available as a generic source", () => {
  const option = sourceTypeOptions.find(
    ({ key }) => key === "rgb/no_processing"
  );

  assert.equal(option?.text, "RGB/NoProcessing");
  assert.equal(option?.visualizerText, "RGB/NoProcessing");
});

test("maps the pre-rebrand maxar key onto the vantor source type", () => {
  assert.equal(normalizeSourceTypeKey("maxar"), "vantor");

  // An image layer saved before the rename must still resolve to a real
  // option, otherwise the dropdown and visualizer fall back to "Unknown".
  const legacy = sourceTypeOptions.find(
    ({ key }) => key === normalizeSourceTypeKey("maxar")
  );
  assert.equal(legacy?.text, "Vantor");
});

test("leaves non-legacy source type keys untouched", () => {
  assert.equal(normalizeSourceTypeKey("planet_scope"), "planet_scope");
  assert.equal(normalizeSourceTypeKey("vantor"), "vantor");
  assert.equal(normalizeSourceTypeKey(undefined), undefined);
  assert.equal(normalizeSourceTypeKey(null), null);
});

test("uses Vantor display metadata for the existing provider key", () => {
  const option = sourceTypeOptions.find(({ key }) => key === "vantor");

  assert.equal(option?.text, "Vantor");
  assert.equal(option?.visualizerText, "Vantor Open Data Program");
  assert.equal(option?.url, "https://vantor.com/");
});
