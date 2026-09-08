// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Feature-scoped HTTP semantics. Do not change legacy apiGet/apiPut behavior.
import { readResponseBuffer } from "../InteractiveLabeler/interactiveLabelerLoading.js";

export async function requestPredictionJson(url, { body, signal, fetchResponse = globalThis.fetch, allowPartialAssessment = false } = {}) {
  signal?.throwIfAborted();
  const timeout = AbortSignal.timeout(120000);
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const response = await fetchResponse(url, {
    method: body === undefined ? "GET" : "PUT",
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    signal: requestSignal, cache: "no-store",
  });
  const buffer = await readResponseBuffer(response, undefined, { signal: requestSignal, maxBytes: 64 * 1024 * 1024 });
  requestSignal.throwIfAborted();
  let data;
  try { data = JSON.parse(new TextDecoder().decode(buffer)); } catch { /* handled below */ }
  const assessmentDiagnostic = allowPartialAssessment && body === undefined &&
    typeof data?.error === "string" &&
    Number.isFinite(data.predictions?.total) && data.predictions.total >= 0 &&
    Number.isFinite(data.populationEstimate?.N) && data.populationEstimate.N >= 0;
  if (!response.ok || (data?.error && !assessmentDiagnostic)) {
    const detail = data?.error;
    const message = typeof detail === "string" ? detail : detail?.message || data?.message;
    const error = new Error(message || `Prediction request failed (HTTP ${response.status}).`);
    error.status = response.status;
    error.code = detail?.code || data?.code;
    throw error;
  }
  if (response.status !== 200 || !data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("The server did not return a completed prediction response.");
  }
  return data;
}

export function predictionErrorMessage(error) {
  switch (error?.code) {
    case "source_changed":
      return "The model predictions changed. Your draft has been kept, but cannot be saved against the new source. Select raw model output to start from the current predictions.";
    case "save_conflict":
      return "Another save is in progress. Your draft has been kept. Retry this save in a moment.";
    case "request_conflict":
      return "This save request ID was already used for different content. Your draft has been kept; do not retry it with changed content.";
    default:
      return error?.message || "The prediction request could not be completed.";
  }
}
