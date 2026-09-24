import test from "node:test";
import assert from "node:assert/strict";

import { filterCountries } from "./countries.js";

const countries = [
  { key: "CA", text: "Canada" },
  { key: "GH", text: "Ghana" },
  { key: "UG", text: "Uganda" },
];

test("filterCountries returns all countries for an empty query", () => {
  assert.deepEqual(filterCountries(countries, "  "), countries);
});

test("filterCountries matches partial country names case-insensitively", () => {
  assert.deepEqual(filterCountries(countries, "ANa"), [
    { key: "CA", text: "Canada" },
    { key: "GH", text: "Ghana" },
  ]);
});

test("filterCountries returns no countries when the query does not match", () => {
  assert.deepEqual(filterCountries(countries, "Mexico"), []);
});