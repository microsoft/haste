import test from "node:test";
import assert from "node:assert/strict";

import { validateEmptyOrInvalid } from "./validation.js";

test("accepts an ampersand in a required name", () => {
  const result = validateEmptyOrInvalid(true, "Name", "Cameron & Scout");

  assert.equal(result, "");
});

test("rejects unsupported punctuation in a required name", () => {
  const result = validateEmptyOrInvalid(true, "Name", "Cameron / Scout");

  assert.equal(
    result,
    "Name only allows letters, numbers, spaces, commas, periods, ampersands, underscores, and hyphens"
  );
});
