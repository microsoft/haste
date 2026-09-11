import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPublishedDatasetsEndpoint,
  preparePublishedDatasetsRequest,
  shouldPollPublishedDatasets,
} from "./publishedDatasetsRequest.js";


test("builds a stable endpoint from every query field", () => {
  const endpoint = buildPublishedDatasetsEndpoint({
    currentPage: 2,
    pageSize: 20,
    sort: { key: "name", dir: "asc" },
    targetFilter: "local",
    statusFilter: "PUBLISHED",
    searchText: "damage",
  });

  assert.equal(
    endpoint,
    "GetPublishedDatasets?page=2&pageSize=20&sortKey=name&sortDirection=asc" +
      "&target=local&status=PUBLISHED&search=damage"
  );
});

test("omits inactive filters from the endpoint", () => {
  const endpoint = buildPublishedDatasetsEndpoint({
    currentPage: 1,
    pageSize: 8,
    sort: { key: "publishedDate", dir: "desc" },
    targetFilter: "all",
    statusFilter: "all",
    searchText: "",
  });

  assert.equal(
    endpoint,
    "GetPublishedDatasets?page=1&pageSize=8" +
      "&sortKey=publishedDate&sortDirection=desc"
  );
});

test("polls only visible active pages without a running request", () => {
  const ready = {
    hasActiveItems: true,
    searchReady: true,
    visibilityState: "visible",
    requestRunning: false,
  };

  assert.equal(shouldPollPublishedDatasets(ready), true);
  for (const override of [
    { hasActiveItems: false },
    { searchReady: false },
    { visibilityState: "hidden" },
    { requestRunning: true },
  ]) {
    assert.equal(
      shouldPollPublishedDatasets({ ...ready, ...override }),
      false
    );
  }
});

test("force refresh aborts a stale same-query request", () => {
  let running = true;
  const calls = [];
  const request = {
    isRunning(key) {
      calls.push(["isRunning", key]);
      return running;
    },
    abort() {
      calls.push(["abort"]);
      running = false;
    },
  };

  const startsRequest = preparePublishedDatasetsRequest(
    request,
    "query",
    true
  );

  assert.equal(startsRequest, true);
  assert.deepEqual(calls, [
    ["isRunning", "query"],
    ["abort"],
    ["isRunning", "query"],
  ]);
});