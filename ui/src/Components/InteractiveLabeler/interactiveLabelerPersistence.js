// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// These synchronous labeler writes require a confirmed outcome. The shared
// legacy apiPut returns a numeric 409, which is not a successful publication.
// Keep this status-aware transport scoped here instead of changing its callers
// throughout the app. buildUrl still supplies the existing API/auth routing.
const WRITE_ENDPOINTS = new Set(["PutInteractiveLabels", "PutBuildingPredictions"]);

function responseMessage(body, fallback) {
  if (typeof body?.error === "string") return body.error;
  if (typeof body?.error?.message === "string") return body.error.message;
  if (typeof body?.message === "string") return body.message;
  return fallback;
}

export function createLabelerWriter(buildUrl, fetchResponse = globalThis.fetch) {
  return async (endpoint, body) => {
    if (!WRITE_ENDPOINTS.has(endpoint)) throw new Error("Unsupported labeler write.");
    let response;
    try {
      response = await fetchResponse(buildUrl(endpoint), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (cause) {
      const error = new Error(
        `The write could not be confirmed (${cause.message || "network failure"}). ` +
        "The server may have received it; check your connection before retrying.",
        { cause },
      );
      error.outcomeUnknown = true;
      throw error;
    }
    let result = null;
    if (response.status !== 204) {
      try { result = await response.json(); } catch { /* status still identifies rejected writes */ }
    }
    // 202 means accepted, not completed. Neither of these endpoints should
    // acknowledge asynchronous work or publish success before paired writes.
    const completed = [200, 201, 204].includes(response.status);
    if (!completed || result?.error || result?.success === false ||
        (response.status !== 204 && result === null)) {
      const error = new Error(responseMessage(
        result, `The write was not confirmed (HTTP ${response.status}).`,
      ));
      error.status = response.status;
      error.code = result?.error?.code || result?.code;
      throw error;
    }
    return result;
  };
}

/** Called by Predict All: local prediction state is committed only on success. */
export async function saveBuildingPredictions(write, request, onCommitted) {
  const result = await write("PutBuildingPredictions", request);
  onCommitted(result);
  return result;
}

/**
 * The two existing endpoints are NOT an atomic clear. Retain local recovery
 * copies until both acknowledge success and report a partial clear explicitly.
 * Never try an automatic rollback that could overwrite another user's labels.
 */
export async function clearLabelsAndPredictions(write, ids, onCommitted) {
  let labelsCleared = false;
  try {
    await write("PutInteractiveLabels", { ...ids, labels: {} });
    labelsCleared = true;
    await write("PutBuildingPredictions", { ...ids, predictions: [] });
  } catch (cause) {
    const message = labelsCleared
      ? "Partial clear: labels were cleared on the server, but clearing predictions could not be confirmed. " +
        "Local labels and predictions have been kept. Retry clearing, or save labels to restore the local label copy."
      : "Clear failed: clearing labels could not be confirmed; prediction clearing was not requested. " +
        "Local labels and predictions have been kept.";
    const error = new Error(`${message} ${cause.message || "Please check your connection."}`, { cause });
    error.labelsCleared = labelsCleared;
    error.status = cause.status;
    error.code = cause.code;
    throw error;
  }
  onCommitted();
}
