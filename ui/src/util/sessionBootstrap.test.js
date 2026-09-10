import assert from "node:assert/strict";
import test from "node:test";

import { apiValidateUser } from "./api.js";


test("session bootstrap updates user and publishing state with one request", async () => {
  const calls = [];
  const updates = [];
  const response = {
    user: {
      userId: "analyst@example.com",
      identityId: "object-id",
      userRoles: ["authenticated", "contributors"],
      settings: { theme: "dark" },
      status: "Active",
    },
    publishing: {
      publishingEnabled: true,
      providers: [{ id: "local" }],
    },
  };

  await apiValidateUser(
    (update) => updates.push(update),
    async (endpoint) => {
      calls.push(endpoint);
      return response;
    }
  );

  assert.deepEqual(calls, ["GetSessionBootstrap"]);
  assert.equal(updates.length, 1);
  assert.deepEqual(updates[0]({ appTitle: "HASTE" }), {
    appTitle: "HASTE",
    userId: "analyst@example.com",
    identityId: "object-id",
    userRoles: ["authenticated", "contributors"],
    userSettings: { theme: "dark" },
    userStatus: "Active",
    publishingEnabled: true,
    publishingProviders: [{ id: "local" }],
  });
});

test("session bootstrap rejects an incomplete response", async () => {
  await assert.rejects(
    apiValidateUser(() => {}, async () => ({ user: {} })),
    /Invalid session bootstrap response/
  );
});

test("pending acceptance stays blocked without follow-up requests", async () => {
  const calls = [];
  const updates = [];
  const pending = {
    user: {
      userId: "analyst@example.com",
      identityId: "object-id",
      userRoles: [],
      settings: {},
      status: "PendingAcceptance",
    },
    publishing: { publishingEnabled: false, providers: [] },
  };
  await apiValidateUser(
    (update) => updates.push(update),
    async (endpoint) => {
      calls.push(endpoint);
      return pending;
    }
  );

  assert.deepEqual(calls, ["GetSessionBootstrap"]);
  assert.equal(updates.length, 1);
  assert.equal(updates[0]({}).userStatus, "PendingAcceptance");
  assert.equal(updates[0]({}).identityId, "object-id");
  assert.deepEqual(updates[0]({}).userRoles, []);
  assert.equal(updates[0]({}).publishingEnabled, false);
});