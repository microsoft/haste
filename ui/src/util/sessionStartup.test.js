import assert from "node:assert/strict";
import test from "node:test";

import { loadSession } from "./sessionStartup.js";


test("successful session startup delegates loading to the route", async () => {
  const errors = [];
  const result = await loadSession({
    validateUser: async () => {},
    setAppParams: () => assert.fail("success must not replace app state"),
    setSessionError: (value) => errors.push(value),
  });

  assert.equal(result, true);
  assert.deepEqual(errors, [false]);
});

test("failed session startup exposes retry state", async () => {
  const errors = [];
  const updates = [];
  const result = await loadSession({
    validateUser: async () => {
      throw new Error("server detail");
    },
    setAppParams: (update) => updates.push(update),
    setSessionError: (value) => errors.push(value),
  });

  assert.equal(result, false);
  assert.deepEqual(errors, [false, true]);
  assert.deepEqual(updates[0]({ retained: true }), {
    retained: true,
    userId: null,
    identityId: null,
    userRoles: [],
    userSettings: {},
    userStatus: null,
    publishingEnabled: false,
    publishingProviders: [],
  });
});
