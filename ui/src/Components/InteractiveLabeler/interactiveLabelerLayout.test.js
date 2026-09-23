// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./InteractiveLabeler.jsx", import.meta.url), "utf8");

test("direct labeler navigation loads its navigation and surface styles", () => {
  assert.ok(
    /import\s+["']\.\.\/\.\.\/assets\/css\/drawingToolbar\.css["']/.test(source),
    "The labeler must not depend on another route loading its stylesheet",
  );
});

test("the selection overlay shares the positioned map area with both canvases", () => {
  const areaStart = source.indexOf('id="interactiveLabelerMapArea"');
  const panelStart = source.indexOf("className={`${styles.sidePanel}", areaStart);
  assert.ok(areaStart >= 0 && panelStart > areaStart);
  const mapArea = source.slice(areaStart, panelStart);
  assert.ok(/position:\s*"relative"/.test(mapArea));
  assert.ok(/ref=\{mapContainerRef\}/.test(mapArea));
  assert.ok(/ref=\{swipeMapContainerRef\}/.test(mapArea));
  assert.ok(/ref=\{boxRef\}/.test(mapArea), "Selection overlay must be inside the map area");
});
