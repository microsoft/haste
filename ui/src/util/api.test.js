import assert from "node:assert/strict";
import test from "node:test";

import { apiGet } from "./api.js";

test("apiGet forwards AbortSignal and request headers", async () => {
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  const options = {
    signal: controller.signal,
    headers: { "If-None-Match": '"etag"' },
  };
  let receivedUrl;
  let receivedOptions;
  globalThis.fetch = async (url, requestOptions) => {
    receivedUrl = url;
    receivedOptions = requestOptions;
    return {
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ value: "loaded" }),
    };
  };

  try {
    const result = await apiGet("GetSomething", options);

    assert.equal(receivedUrl, "GetSomething");
    assert.equal(receivedOptions, options);
    assert.deepEqual(result, { value: "loaded" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
