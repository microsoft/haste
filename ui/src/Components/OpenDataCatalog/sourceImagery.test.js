import test from "node:test";
import assert from "node:assert/strict";

import { sourceImageryRef, OPEN_DATA_PROGRAMS } from "./openDataCatalog.js";

const vantorScene = {
  id: "scene-a",
  source: "Vantor",
  title: "Caracas post-event",
  datetime: "2024-08-30T00:00:00Z",
  cogUrl: "https://vantor-opendata.s3.amazonaws.com/e/scene-a.tif",
  itemHref: "https://vantor-opendata.s3.amazonaws.com/e/scene-a.json",
  phase: "post",
};

test("builds an attributable ref from a Vantor open-data scene", () => {
  const ref = sourceImageryRef(vantorScene, "post");
  assert.equal(ref.programId, "vantor-open-data");
  assert.equal(ref.programName, OPEN_DATA_PROGRAMS.Vantor.programName);
  assert.equal(ref.license, "CC-BY-NC-4.0");
  assert.equal(ref.attributable, true);
  assert.equal(ref.href, vantorScene.itemHref);
  assert.equal(ref.sceneId, "scene-a");
  assert.equal(ref.phase, "post");
  assert.equal(ref.capturedDate, vantorScene.datetime);
  // UI-only correlation field (stripped before send).
  assert.equal(ref.sourceUrl, vantorScene.cogUrl);
});

test("builds a ref for a Planet open-data scene", () => {
  const ref = sourceImageryRef(
    { ...vantorScene, source: "Planet" },
    "pre"
  );
  assert.equal(ref.programId, "planet-open-data");
  assert.equal(ref.phase, "pre");
});

test("returns null for a scene without an item href (no provenance target)", () => {
  assert.equal(sourceImageryRef({ ...vantorScene, itemHref: null }, "post"), null);
});

test("returns null for a scene not from a registered open-data program", () => {
  assert.equal(sourceImageryRef({ ...vantorScene, source: "SomeVendor" }, "post"), null);
  assert.equal(sourceImageryRef(null, "post"), null);
});

test("falls back to the scene's own phase when none is passed", () => {
  const ref = sourceImageryRef(vantorScene);
  assert.equal(ref.phase, "post");
});
