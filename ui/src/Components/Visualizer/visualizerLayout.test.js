// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Results navigation overrides the shared column layout independently of CSS load order", async () => {
  const css = await readFile(new URL("../../assets/css/visualizer.css", import.meta.url), "utf8");
  const navigation = css.match(/\.visualizer-container\s+\.labeling-navigation-controls\s*\{([^}]+)\}/)?.[1];
  assert.ok(navigation, "Use a Results-scoped selector more specific than the shared toolbar");
  assert.match(navigation, /flex-direction:\s*row\s*;/);
  assert.match(navigation, /align-items:\s*center\s*;/);
});
