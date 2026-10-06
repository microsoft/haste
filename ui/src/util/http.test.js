import test from "node:test";
import assert from "node:assert/strict";

import {
  fetchJsonResponse,
  HttpResponseError,
  NetworkRequestError,
} from "./http.js";

function response({ status = 200, data = null, etag = null } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => (name === "etag" ? etag : null) },
    json: async () => data,
  };
}

test("returns parsed JSON and ETag", async () => {
  const fetchImpl = async () =>
    response({ data: { projectId: "project-1" }, etag: '"etag"' });

  const result = await fetchJsonResponse("/project", {}, fetchImpl);

  assert.deepEqual(result, {
    data: { projectId: "project-1" },
    etag: '"etag"',
    status: 200,
  });
});

test("returns an empty successful result for 304", async () => {
  let jsonCalled = false;
  const fetchImpl = async () => ({
    ...response({ status: 304, etag: '"etag"' }),
    json: async () => {
      jsonCalled = true;
    },
  });

  const result = await fetchJsonResponse("/project", {}, fetchImpl);

  assert.deepEqual(result, { data: null, etag: '"etag"', status: 304 });
  assert.equal(jsonCalled, false);
});

test("returns null for a successful empty response", async () => {
  const result = await fetchJsonResponse(
    "/project",
    {},
    async () => response({ status: 204 })
  );

  assert.deepEqual(result, { data: null, etag: null, status: 204 });
});

test("preserves HTTP status for failed responses", async () => {
  await assert.rejects(
    fetchJsonResponse(
      "/project",
      {},
      async () => response({ status: 503 })
    ),
    (error) => error instanceof HttpResponseError && error.status === 503
  );
});

test("classifies network failures without hiding aborts", async () => {
  await assert.rejects(
    fetchJsonResponse("/project", {}, async () => {
      throw new TypeError("offline");
    }),
    (error) => error instanceof NetworkRequestError
      && error.cause?.message === "offline"
  );

  const abort = new Error("aborted");
  abort.name = "AbortError";
  await assert.rejects(
    fetchJsonResponse("/project", {}, async () => { throw abort; }),
    (error) => error === abort
  );
});

test("passes request options to fetch", async () => {
  const controller = new AbortController();
  const options = {
    signal: controller.signal,
    headers: { "If-None-Match": '"etag"' },
  };
  let receivedOptions;

  await fetchJsonResponse("/project", options, async (_url, received) => {
    receivedOptions = received;
    return response({ data: {} });
  });

  assert.equal(receivedOptions, options);
});