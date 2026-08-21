import test from "node:test";
import assert from "node:assert/strict";

import { sourceTypeOptions } from "./sourceTypeOptions.js";

test("lists only the supported visible imagery source types", () => {
  const visibleSourceKeys = sourceTypeOptions
    .filter((option) => option.showInDropdown)
    .map((option) => option.key);

  assert.deepEqual(visibleSourceKeys, [
    "n/a",
    "rgb/no_processing",
    "maxar",
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

test("uses Vantor display metadata for the existing provider key", () => {
  const option = sourceTypeOptions.find(({ key }) => key === "maxar");

  assert.equal(option?.text, "Vantor");
  assert.equal(option?.visualizerText, "Vantor Open Data Program");
  assert.equal(option?.url, "https://vantor.com/");
});
