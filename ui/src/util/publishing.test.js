import test from "node:test";
import assert from "node:assert/strict";

import { summarizeSourceImagery } from "./publishing.js";

test("summarizeSourceImagery dedupes by program with fully-qualified scenes", () => {
  const rows = summarizeSourceImagery([
    { programId: "vantor-open-data", programName: "Vantor", license: "CC-BY-NC-4.0", href: "https://a.example/1.json", title: "A" },
    { programId: "vantor-open-data", programName: "Vantor", license: "CC-BY-NC-4.0", href: "https://a.example/2.json", title: "B" },
    { programId: "planet-open-data", programName: "Planet", license: "CC-BY-NC-4.0", href: "https://a.example/3.json" },
  ]);
  assert.equal(rows.length, 2);
  const vantor = rows.find((r) => r.program === "Vantor");
  assert.equal(vantor.scenes.length, 2);
  assert.equal(vantor.scenes[0].href, "https://a.example/1.json");
  assert.equal(vantor.scenes[0].title, "A");
  assert.equal(vantor.license, "CC-BY-NC-4.0");
  const planet = rows.find((r) => r.program === "Planet");
  assert.equal(planet.scenes.length, 1);
  // Falls back to the href when no title is given.
  assert.equal(planet.scenes[0].title, "https://a.example/3.json");
});

test("summarizeSourceImagery handles empty/undefined", () => {
  assert.deepEqual(summarizeSourceImagery(), []);
  assert.deepEqual(summarizeSourceImagery([]), []);
});
