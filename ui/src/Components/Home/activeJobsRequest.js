export const ACTIVE_JOBS_ENDPOINT = "GetActiveJobs";

export function activeJobsHeaders(etag) {
  const headers = {};
  if (etag) headers["If-None-Match"] = etag;
  return headers;
}

export function shouldPollActiveJobs({ visibilityState, requestRunning }) {
  return visibilityState === "visible" && !requestRunning;
}

export function activeJobsAfterResponse(currentJobs, { data, status }) {
  return status === 304 ? currentJobs : data?.jobs || [];
}
