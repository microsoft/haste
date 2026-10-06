import assert from "node:assert/strict";
import test from "node:test";

import { apiGet, buildSignInUrl } from "./api.js";
import { HttpResponseError } from "./http.js";

test("sign-in return targets stay same-origin and preserve the destination", () => {
  const url = new URL(
    buildSignInUrl("/labeling-tool?project=abc#step-2", "https://haste.example"),
    "https://haste.example"
  );

  assert.equal(url.pathname, "/.auth/login/aad");
  assert.equal(
    url.searchParams.get("post_login_redirect_uri"),
    "https://haste.example/labeling-tool?project=abc#step-2"
  );

  const unsafe = new URL(
    buildSignInUrl("//attacker.example/steal", "https://haste.example"),
    "https://haste.example"
  );
  assert.equal(
    unsafe.searchParams.get("post_login_redirect_uri"),
    "https://haste.example/"
  );
});

test("apiGet preserves HTTP status for session error classification", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    headers: { get: () => null },
  });

  try {
    await assert.rejects(
      apiGet("GetSessionBootstrap"),
      (error) => error instanceof HttpResponseError && error.status === 401
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

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
