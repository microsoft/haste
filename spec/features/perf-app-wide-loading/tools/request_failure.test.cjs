const assert = require("node:assert/strict");
const test = require("node:test");

const { isExpectedNavigationAbort } = require("./request_failure.cjs");

function request(errorText) {
  return { failure: () => (errorText ? { errorText } : null) };
}

test("accepts browser cancellation caused by navigation", () => {
  for (const message of ["net::ERR_ABORTED", "AbortError"]) {
    const abandoned = request(message);
    assert.equal(isExpectedNavigationAbort(abandoned, new Set([abandoned])), true);
  }
});

test("does not suppress target-route or cold-direct aborts", () => {
  const target = request("net::ERR_ABORTED");
  assert.equal(isExpectedNavigationAbort(target), false);
  assert.equal(isExpectedNavigationAbort(target, new Set([request("AbortError")])), false);
});

test("rejects genuine request failures", () => {
  const failed = request("net::ERR_FAILED");
  assert.equal(isExpectedNavigationAbort(failed, new Set([failed])), false);
  assert.equal(isExpectedNavigationAbort(request(null)), false);
});
