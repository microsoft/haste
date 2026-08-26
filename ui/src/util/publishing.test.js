import test from "node:test";
import assert from "node:assert/strict";

import { summarizeSourceImagery } from "./publishing.js";

test("summarizeSourceImagery dedupes by program with scene counts", () => {
  const rows = summarizeSourceImagery([
    { programId: "vantor-open-data", programName: "Vantor", license: "CC-BY-NC-4.0" },
    { programId: "vantor-open-data", programName: "Vantor", license: "CC-BY-NC-4.0" },
    { programId: "planet-open-data", programName: "Planet", license: "CC-BY-NC-4.0" },
  ]);
  assert.equal(rows.length, 2);
  const vantor = rows.find((r) => r.program === "Vantor");
  assert.equal(vantor.count, 2);
  assert.equal(vantor.license, "CC-BY-NC-4.0");
  assert.equal(rows.find((r) => r.program === "Planet").count, 1);
});

test("summarizeSourceImagery handles empty/undefined", () => {
  assert.deepEqual(summarizeSourceImagery(), []);
  assert.deepEqual(summarizeSourceImagery([]), []);
});
