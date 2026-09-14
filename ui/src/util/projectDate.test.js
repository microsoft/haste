import test from "node:test";
import assert from "node:assert/strict";

import { formatProjectDate, parseProjectDate } from "./projectDate.js";

test("parseProjectDate parses a valid date without using today", () => {
  const date = parseProjectDate("09/01/2026");

  assert.equal(date?.getFullYear(), 2026);
  assert.equal(date?.getMonth(), 8);
  assert.equal(date?.getDate(), 1);
});

test("parseProjectDate accepts a valid leap day", () => {
  assert.equal(formatProjectDate(parseProjectDate("02/29/2024")), "02/29/2024");
});

test("parseProjectDate rejects invalid and ambiguous dates", () => {
  assert.equal(parseProjectDate("02/29/2025"), null);
  assert.equal(parseProjectDate("02/31/2026"), null);
  assert.equal(parseProjectDate("2026-09-01"), null);
});

test("formatProjectDate uses the explicit MM/DD/YYYY format", () => {
  assert.equal(formatProjectDate(new Date(2026, 8, 1)), "09/01/2026");
});