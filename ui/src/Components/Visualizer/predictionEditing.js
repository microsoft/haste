// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's pure editing decisions, adapted to COMPLETE explicit-pin snapshots.
import { CLASS_DAMAGED, CLASS_NOT_DAMAGED, CLASS_UNKNOWN, PREDICTION_CLASSES } from "./predictionClassify.js";

export function deriveClass(damage, unknown, threshold = 0, unknownThreshold = 0) {
  if (!Number.isFinite(damage) || !Number.isFinite(unknown)) return CLASS_UNKNOWN;
  if (unknown > unknownThreshold) return CLASS_UNKNOWN;
  return damage > threshold ? CLASS_DAMAGED : CLASS_NOT_DAMAGED;
}
export const canAdjustThresholds = (source) =>
  (source.predictionVersion ?? 0) === 0 && source.flavor === "inference" && source.supportsThreshold === true;

export function initialDraft(attrs, session) {
  const overrides = {};
  if (attrs.predictionVersion > 0) {
    attrs.overrideClasses.forEach((cls, index) => { if (cls !== null) overrides[attrs.ids[index]] = cls; });
  }
  return {
    threshold: session.threshold, unknownThreshold: session.unknownThreshold, overrides,
  };
}
export function setOverrides(overrides, ids, cls) {
  if (!PREDICTION_CLASSES.includes(cls)) throw new Error("Invalid prediction class.");
  return { ...overrides, ...Object.fromEntries(ids.map((id) => [id, cls])) };
}
export function modelClassAt(attrs, index) {
  return attrs.predictionVersion > 0 ? attrs.modelClasses[index] : attrs.classes[index];
}
export function classifyDraft(attrs, source, draft, baseline) {
  const thresholdsChanged = draft.threshold !== baseline.threshold || draft.unknownThreshold !== baseline.unknownThreshold;
  const rethreshold = canAdjustThresholds(source) && thresholdsChanged;
  const counts = Object.fromEntries(PREDICTION_CLASSES.map((cls) => [cls, 0]));
  const classes = attrs.ids.map((id, index) => {
    const cls = draft.overrides[id] ?? (rethreshold
      ? deriveClass(attrs.damage[index], attrs.unknown[index], draft.threshold, draft.unknownThreshold)
      : attrs.classes[index]);
    counts[cls]++;
    return cls;
  });
  const editedIds = new Set(attrs.ids.filter((id) => draft.overrides[id] !== undefined));
  const changedFromModel = classes.filter((cls, i) => cls !== modelClassAt(attrs, i)).length;
  return { classes, counts, editedIds, changedFromModel, total: attrs.n };
}
export function overrideList(overrides) {
  // Do not drop pins merely because they equal the derived class TODAY.
  return Object.entries(overrides).map(([id, cls]) => {
    if (!Number.isSafeInteger(Number(id)) || Number(id) < 0 || !PREDICTION_CLASSES.includes(cls)) {
      throw new Error("Invalid explicit prediction assignment.");
    }
    return { id: Number(id), class: cls };
  }).sort((a, b) => a.id - b.id);
}
export function draftFingerprint(draft) {
  return JSON.stringify([draft.threshold, draft.unknownThreshold, overrideList(draft.overrides)]);
}
export const isDraftDirty = (draft, baseline) => draftFingerprint(draft) !== draftFingerprint(baseline);
export function countManualChanges(draft, baseline) {
  const ids = new Set([...Object.keys(draft.overrides), ...Object.keys(baseline.overrides)]);
  return [...ids].filter((id) => draft.overrides[id] !== baseline.overrides[id]).length;
}
export function undoManualChanges(draft, baseline) {
  return { ...draft, overrides: { ...baseline.overrides } };
}

export function buildSavePayload(ids, source, draft, clientRequestId) {
  return {
    ...ids, predictionRevision: source.predictionRevision,
    baseVersion: source.predictionVersion ?? 0, clientRequestId,
    threshold: draft.threshold, unknownThreshold: draft.unknownThreshold,
    overrides: overrideList(draft.overrides),
  };
}

/** A lost-response retry must send the identical UUID AND body. */
export function saveAttempt(previous, ids, source, draft, uuid) {
  const fingerprint = JSON.stringify([ids, source.predictionRevision, source.predictionVersion ?? 0, draftFingerprint(draft)]);
  return previous?.fingerprint === fingerprint ? previous : {
    fingerprint, body: buildSavePayload(ids, source, draft, uuid()),
  };
}

export function filteredRows(attrs, classification, filter) {
  return attrs.ids.map((_id, i) => i).filter((i) =>
    filter === "all" || (filter === "edited" ? classification.editedIds.has(attrs.ids[i]) : classification.classes[i] === filter),
  );
}
export function nextReviewIndex(rows, current, direction, hasLocation = () => true) {
  if (!rows.length) return null;
  const position = rows.indexOf(current);
  let start = position;
  if (position < 0) {
    // Painting can move the selected building out of the active filter. Keep
    // walking from its insertion point rather than restarting at the first row.
    if (direction > 0) start = rows.reduce((before, row, i) => row < current ? i : before, -1);
    else {
      const after = rows.findIndex((row) => row > current);
      start = after < 0 ? rows.length : after;
    }
  }
  let fallback;
  for (let step = 1; step <= rows.length; step++) {
    const row = rows[(start + step * direction + rows.length * 2) % rows.length];
    fallback ??= row;
    if (hasLocation(row)) return row;
  }
  return fallback;
}

export function validateEditSession(session, source, attrs) {
  if (session.predictionRevision !== source.predictionRevision ||
      (session.currentPredictionRevision && session.currentPredictionRevision !== session.predictionRevision)) {
    const error = new Error("The prediction source changed after these results were loaded.");
    error.code = "source_changed";
    throw error;
  }
  if (session.predictionVersion !== (source.predictionVersion ?? 0) ||
      session.buildingCount !== attrs.n ||
      session.flavor !== source.flavor || session.supportsThreshold !== source.supportsThreshold) {
    throw new Error("The edit session does not match the displayed predictions.");
  }
  if (session.editReadiness?.ready !== true) {
    throw new Error(session.editReadiness?.detail || "These predictions are not available for editing.");
  }
  for (const name of ["threshold", "unknownThreshold"]) {
    if (!Number.isFinite(session[name]) || session[name] < 0 || session[name] > 1) throw new Error("The edit session contains invalid thresholds.");
  }
  if (attrs.predictionVersion > 0 &&
      (attrs.threshold !== session.threshold || attrs.unknownThreshold !== session.unknownThreshold)) {
    throw new Error("The edit session thresholds do not match this version.");
  }
  return session;
}
