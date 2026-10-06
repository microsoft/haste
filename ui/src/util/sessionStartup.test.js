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
  assert.deepEqual(errors, [null]);
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
    retryDelaysMs: [],
    now: () => new Date("2026-10-05T10:00:00.000Z"),
    createDiagnosticReference: () => "ref-123",
  });

  assert.equal(result, false);
  assert.deepEqual(errors, [null, {
    kind: "unknown",
    status: null,
    reference: "ref-123",
    timestamp: "2026-10-05T10:00:00.000Z",
  }]);
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

test("retries transient startup failures within the configured bound", async () => {
  let attempts = 0;
  const waits = [];
  const result = await loadSession({
    validateUser: async () => {
      attempts += 1;
      if (attempts < 3) {
        const error = new Error("temporary service failure");
        error.status = 503;
        throw error;
      }
    },
    setAppParams: () => {},
    setSessionError: () => {},
    retryDelaysMs: [10, 20],
    waitImpl: async (delay) => waits.push(delay),
  });

  assert.equal(result, true);
  assert.equal(attempts, 3);
  assert.deepEqual(waits, [10, 20]);
});

test("does not retry forbidden sessions and classifies them separately", async () => {
  let attempts = 0;
  const errors = [];
  const forbidden = new Error("forbidden");
  forbidden.status = 403;

  await loadSession({
    validateUser: async () => {
      attempts += 1;
      throw forbidden;
    },
    setAppParams: () => {},
    setSessionError: (error) => errors.push(error),
    waitImpl: async () => assert.fail("403 must not be retried"),
  });

  assert.equal(attempts, 1);
  assert.equal(errors[1].kind, "forbidden");
  assert.equal(errors[1].status, 403);
});

test("classifies expired authentication without automatically redirecting", async () => {
  const errors = [];
  const unauthorized = new Error("unauthorized");
  unauthorized.status = 401;

  await loadSession({
    validateUser: async () => { throw unauthorized; },
    setAppParams: () => {},
    setSessionError: (error) => errors.push(error),
  });

  assert.equal(errors[1].kind, "unauthorized");
});
