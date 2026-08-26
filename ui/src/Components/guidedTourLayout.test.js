import test from "node:test";
import assert from "node:assert/strict";

import { getTourCardStyle } from "./guidedTourLayout.js";

test("getTourCardStyle keeps a card visible for a viewport-sized target", () => {
  const viewportHeight = 768;
  const style = getTourCardStyle(
    { top: 60, left: 0, width: 1200, height: 690 },
    1280,
    viewportHeight
  );

  assert.ok(style.top >= 16);
  assert.ok(style.top + style.maxHeight <= viewportHeight - 16);
});

test("getTourCardStyle places a card below a small target when space exists", () => {
  const style = getTourCardStyle(
    { top: 40, left: 100, width: 120, height: 40 },
    1280,
    768
  );

  assert.equal(style.top, 94);
  assert.equal(style.bottom, undefined);
});