import { activeJobIndicatorProps } from "./activeJobsRequest.js";

test("missing progress uses the legacy status fallback without erasing zero", () => {
  assert.equal(activeJobIndicatorProps({ currentStep: null }).currentStep, undefined);
  assert.equal(activeJobIndicatorProps({ currentStep: 0 }).currentStep, 0);
  assert.equal(activeJobIndicatorProps({ status: "Queued" }).status, "Queued");
});
import assert from "node:assert/strict";
import test from "node:test";

import {
  ACTIVE_JOBS_ENDPOINT,
  activeJobsAfterResponse,
  activeJobsHeaders,
  shouldPollActiveJobs,
} from "./activeJobsRequest.js";

test("uses one stable Active Jobs endpoint", () => {
  assert.equal(ACTIVE_JOBS_ENDPOINT, "GetActiveJobs");
});

test("retains current jobs after an unchanged response", () => {
  const current = [{ key: "job-1" }];

  assert.equal(
    activeJobsAfterResponse(current, { data: null, status: 304 }),
    current
  );
  assert.deepEqual(
    activeJobsAfterResponse(current, {
      data: { jobs: [{ key: "job-2" }] },
      status: 200,
    }),
    [{ key: "job-2" }]
  );
});

test("omits the conditional header before the first response", () => {
  assert.deepEqual(activeJobsHeaders(null), {});
});

test("adds a conditional header when available", () => {
  assert.deepEqual(activeJobsHeaders('"etag"'), {
    "If-None-Match": '"etag"',
  });
});

test("polls only while visible and idle", () => {
  assert.equal(
    shouldPollActiveJobs({
      visibilityState: "visible",
      requestRunning: false,
    }),
    true
  );
  assert.equal(
    shouldPollActiveJobs({
      visibilityState: "hidden",
      requestRunning: false,
    }),
    false
  );
  assert.equal(
    shouldPollActiveJobs({
      visibilityState: "visible",
      requestRunning: true,
    }),
    false
  );
});

test("compact active jobs preserve pretrained inference progress without client-side training fan-out", () => {
  for (const status of ["Queued", "InProgress"]) {
    const job = Object.freeze({
      key: "inference:catalog-run", kind: "Inference", projectId: "project-1",
      imageLayerId: "layer-1", modelId: "catalog-run", name: "Catalog inference fixture",
      indicator: Object.freeze({ status, currentStep: 1, totalSteps: 7, progressPct: 15 }),
    });
    const jobs = activeJobsAfterResponse([], { status: 200, data: { jobs: [job] } });
    assert.deepEqual(jobs, [job]);
    assert.deepEqual(activeJobIndicatorProps(jobs[0].indicator), job.indicator);
    assert.equal(activeJobsAfterResponse(jobs, { status: 304, data: null }), jobs);
  }
});
