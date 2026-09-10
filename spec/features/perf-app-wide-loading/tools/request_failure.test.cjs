const assert = require("node:assert/strict");
const test = require("node:test");

const { isExpectedNavigationAbort } = require("./request_failure.cjs");

function request(errorText) {
  return { failure: () => (errorText ? { errorText } : null) };
}

test("accepts browser cancellation caused by navigation", () => {
  assert.equal(isExpectedNavigationAbort(request("net::ERR_ABORTED")), true);
  assert.equal(isExpectedNavigationAbort(request("AbortError")), true);
});

test("rejects genuine request failures", () => {
  assert.equal(isExpectedNavigationAbort(request("net::ERR_FAILED")), false);
  assert.equal(isExpectedNavigationAbort(request(null)), false);
});
