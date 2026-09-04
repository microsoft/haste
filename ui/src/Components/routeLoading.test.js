import assert from "node:assert/strict";
import test from "node:test";

import { getRouteLoadingLabel } from "./routeLoading.js";

test("uses one stable Dashboard label across startup phases", () => {
  assert.equal(getRouteLoadingLabel("/"), "Loading dashboard");
  assert.equal(getRouteLoadingLabel("/home"), "Loading dashboard");
});

test("uses the generic label for other routes", () => {
  assert.equal(getRouteLoadingLabel("/projects"), "Loading page");
});
