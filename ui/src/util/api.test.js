import test from "node:test";
import assert from "node:assert/strict";

import {
  apiFetch,
  isAbortError,
  shouldAppendSubscriptionKey,
} from "./apiRequest.js";

test("relative API URLs rely on the local proxy subscription header", () => {
  assert.equal(
    shouldAppendSubscriptionKey("/api/haste/", "development-key"),
    false
  );
});

test("absolute HTTPS API URLs append their configured subscription key", () => {
  assert.equal(
    shouldAppendSubscriptionKey(
      "https://haste.example/api/",
      "deployment-key"
    ),
    true
  );
});

test("apiFetch forwards the caller AbortSignal to fetch", async () => {
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  let receivedOptions;
  globalThis.fetch = async (_url, options) => {
    receivedOptions = options;
    return {
      ok: true,
      json: async () => ({ ok: true }),
    };
  };

  try {
    const response = await apiFetch("/api/test", {
      signal: controller.signal,
    });
    const result = await response.json();

    assert.deepEqual(result, { ok: true });
    assert.equal(receivedOptions.signal, controller.signal);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("apiFetch preserves AbortError for navigation cleanup", async () => {
  const originalFetch = globalThis.fetch;
  const abortError = new Error("This operation was aborted");
  abortError.name = "AbortError";
  globalThis.fetch = async () => {
    throw abortError;
  };

  try {
    await assert.rejects(
      apiFetch("/api/test"),
      (error) => error === abortError && isAbortError(error)
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});