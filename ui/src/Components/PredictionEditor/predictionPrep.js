// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Pure preparation/polling helpers for the Prediction Editor.
//
// The editor needs two derived artifacts before it can draw anything: the
// footprint PMTiles archive (kind=footprint_pmtiles) and the per-building
// score sidecar (kind=prediction_attrs). Both are produced by a queued job —
// they are never built inline in an HTTP handler because tippecanoe has to
// run — so opening the editor for a model nobody has prepared yet means:
//
//   1. PUT PutPreparePredictionTilesQueueMessage to enqueue the job, then
//   2. poll GetPredictionEditSession until `tilesReady && attrsReady`.
//
// Everything about "should we still be polling, have we given up, is this
// failure terminal, which attempt are we on" lives here as plain functions
// over plain data: no React, no timers, no fetch. The component owns the
// setTimeout; this module owns the decisions, so they can be unit-tested with
// `node --test` (see predictionClassify.test.js).
//
// Status values follow the repo-wide vocabulary (hastegeo StatusTypes):
// Queued / InProgress / Processed / Failed / Cancelled. Anything else — a
// missing field, a null, a value from a newer backend — is treated as
// "unknown but not terminal", which degrades to "keep waiting" rather than
// showing the user a spurious error.

export const PREP_STATUS_QUEUED = "Queued";
export const PREP_STATUS_IN_PROGRESS = "InProgress";
export const PREP_STATUS_PROCESSED = "Processed";
export const PREP_STATUS_FAILED = "Failed";
export const PREP_STATUS_CANCELLED = "Cancelled";

const KNOWN_STATUSES = [
  PREP_STATUS_QUEUED,
  PREP_STATUS_IN_PROGRESS,
  PREP_STATUS_PROCESSED,
  PREP_STATUS_FAILED,
  PREP_STATUS_CANCELLED,
];

// Only these two mean "this job is never finishing on its own".
const TERMINAL_STATUSES = [PREP_STATUS_FAILED, PREP_STATUS_CANCELLED];

// ── Wait-state machine ──────────────────────────────────────────────────────
// REQUESTING  the enqueue PUT is in flight; nothing to poll yet.
// WAITING     the job is queued/running; poll again after the interval.
// READY       both artifacts exist; the editor can load them.
// FAILED      terminal (Failed/Cancelled, or the enqueue call itself blew up);
//             stop polling and offer a forced retry.
// TIMED_OUT   the attempt cap was reached; stop polling and tell the user to
//             check back later.
export const PREP_PHASE_REQUESTING = "requesting";
export const PREP_PHASE_WAITING = "waiting";
export const PREP_PHASE_READY = "ready";
export const PREP_PHASE_FAILED = "failed";
export const PREP_PHASE_TIMED_OUT = "timedOut";

// How long to wait between GetPredictionEditSession polls.
//
// 5s is the same cadence PublishedDatasets.jsx already uses for its active
// publishing jobs, so the app has one polling rhythm rather than several. It
// is short enough that a job which finishes while the user is watching lights
// up the map within a few seconds (the prep job takes minutes, not
// milliseconds, so anything faster only adds load), and long enough that a
// single parked tab costs the function app 12 cheap metadata reads a minute
// instead of hundreds.
export const PREP_POLL_INTERVAL_MS = 5000;

// Give up after this many polls: 360 x 5s = 30 minutes of waiting.
//
// The job has to acquire a container runner before tippecanoe even starts, so
// several minutes is normal and a large layer can legitimately take much
// longer than that; 30 minutes is generous enough that we never abandon a
// healthy job, while still guaranteeing a stuck or dead-lettered one cannot
// leave a forgotten tab polling until the browser is closed.
export const MAX_PREP_POLL_ATTEMPTS = 360;

/**
 * Canonical form of a status string, or "" when it is missing/unrecognized.
 * Matching is case-insensitive and whitespace-tolerant so a backend that
 * writes "queued" or " InProgress " still lines up.
 */
export function normalizePrepStatus(value) {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (trimmed === "") return "";
  const match = KNOWN_STATUSES.find(
    (status) => status.toLowerCase() === trimmed.toLowerCase()
  );
  return match || "";
}

/** True for the statuses a job never recovers from without a new request. */
export function isTerminalPrepStatus(value) {
  return TERMINAL_STATUSES.indexOf(normalizePrepStatus(value)) !== -1;
}

/**
 * True once BOTH artifacts exist. Deliberately strict about `true`: a missing
 * flag from an older backend means "not ready", never "assume ready".
 */
export function isPrepReady(session) {
  return session?.tilesReady === true && session?.attrsReady === true;
}

/** Human sentence naming what is still outstanding, for the waiting card. */
export function describeOutstandingArtifacts(session) {
  const missing = [];
  if (session?.tilesReady !== true) missing.push("footprint tiles");
  if (session?.attrsReady !== true) {
    missing.push("per-building prediction scores");
  }
  if (missing.length === 0) return "";
  return `Still generating ${missing.join(" and ")}.`;
}

/** Label for the status chip; unknown/missing reads as "Starting". */
export function prepStatusLabel(value) {
  switch (normalizePrepStatus(value)) {
    case PREP_STATUS_QUEUED:
      return "Queued";
    case PREP_STATUS_IN_PROGRESS:
      return "In progress";
    case PREP_STATUS_PROCESSED:
      return "Finishing up";
    case PREP_STATUS_FAILED:
      return "Failed";
    case PREP_STATUS_CANCELLED:
      return "Cancelled";
    default:
      return "Starting";
  }
}

/** The attempt counter after one more poll. Junk input restarts at 1. */
export function nextPollAttempt(attempt) {
  const current =
    typeof attempt === "number" && Number.isFinite(attempt) && attempt > 0
      ? Math.floor(attempt)
      : 0;
  return current + 1;
}

/** True only in the one phase that schedules another poll. */
export function shouldPollPrep(phase) {
  return phase === PREP_PHASE_WAITING;
}

/**
 * Decide what the editor should do having just observed `session` after
 * `attempt` polls (0 when the observation came from the enqueue response
 * rather than a poll).
 *
 * Readiness is checked FIRST and on purpose: if the artifacts are on disk it
 * does not matter that some earlier run left a Failed status behind — the
 * editor can open, so it opens.
 */
export function evaluatePrepState(
  session,
  attempt = 0,
  maxAttempts = MAX_PREP_POLL_ATTEMPTS
) {
  const status = normalizePrepStatus(
    session?.predictionTilesStatus ?? session?.status
  );
  const statusMessage =
    typeof session?.predictionTilesStatusMessage === "string"
      ? session.predictionTilesStatusMessage
      : "";
  const base = { status, statusMessage, attempt, error: "" };

  if (isPrepReady(session)) {
    return { ...base, phase: PREP_PHASE_READY, shouldPoll: false, ready: true };
  }
  if (isTerminalPrepStatus(status)) {
    return { ...base, phase: PREP_PHASE_FAILED, shouldPoll: false, ready: false };
  }
  if (attempt >= maxAttempts) {
    return {
      ...base,
      phase: PREP_PHASE_TIMED_OUT,
      shouldPoll: false,
      ready: false,
    };
  }
  return { ...base, phase: PREP_PHASE_WAITING, shouldPoll: true, ready: false };
}

/**
 * Next wait-state after a poll request itself failed (network blip, a 502
 * from the proxy, ...). A transient error must not kill a healthy wait, so we
 * keep the last known status, count the attempt, and carry the message for
 * display — until the cap turns it into a give-up.
 */
export function prepStateAfterPollError(
  current,
  message,
  maxAttempts = MAX_PREP_POLL_ATTEMPTS
) {
  const attempt = nextPollAttempt(current?.attempt);
  const error =
    typeof message === "string" && message.trim() !== ""
      ? message.trim()
      : "The preparation status could not be read.";
  const carried = {
    status: normalizePrepStatus(current?.status),
    statusMessage:
      typeof current?.statusMessage === "string" ? current.statusMessage : "",
    attempt,
    error,
  };
  if (attempt >= maxAttempts) {
    return {
      ...carried,
      phase: PREP_PHASE_TIMED_OUT,
      shouldPoll: false,
      ready: false,
    };
  }
  return {
    ...carried,
    phase: PREP_PHASE_WAITING,
    shouldPoll: true,
    ready: false,
  };
}

/** The exact PUT body for PutPreparePredictionTilesQueueMessage. */
export function buildPrepRequest({
  projectId,
  imageLayerId,
  modelId,
  force = false,
}) {
  const body = { projectId, imageLayerId, modelId };
  // `force` is optional in the contract: only send it when re-queuing a job
  // that already failed, so a routine open can never stomp a running job.
  if (force) body.force = true;
  return body;
}

/**
 * Fold the enqueue response back into the session object so the readiness
 * flags and status the editor renders come from one place.
 *
 * apiPut surfaces a 409 as the bare status code, and any non-object response
 * is ignored — in both cases the caller keeps waiting on the session it
 * already has rather than crashing on `undefined.tilesReady`.
 */
export function applyPrepResponse(session, response) {
  const base = session || {};
  if (!response || typeof response !== "object" || Array.isArray(response)) {
    return base;
  }
  const next = { ...base };
  if (typeof response.tilesReady === "boolean") {
    next.tilesReady = response.tilesReady;
  }
  if (typeof response.attrsReady === "boolean") {
    next.attrsReady = response.attrsReady;
  }
  const status = normalizePrepStatus(
    response.predictionTilesStatus ?? response.status
  );
  if (status) next.predictionTilesStatus = status;
  const message =
    response.predictionTilesStatusMessage ?? response.statusMessage;
  if (typeof message === "string") {
    next.predictionTilesStatusMessage = message;
  }
  return next;
}
