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
  source.flavor === "inference" && source.supportsThreshold === true;

export function initialDraft(attrs, source) {
  for (const name of ["threshold", "unknownThreshold"]) {
    if (!Number.isFinite(source[name]) || source[name] < 0 || source[name] > 1) {
      throw new Error("The prediction source contains invalid thresholds.");
    }
    if (attrs.predictionVersion > 0 && attrs[name] !== source[name]) {
      throw new Error("The prediction source thresholds do not match this version.");
    }
  }
  const overrides = {};
  if (attrs.predictionVersion > 0) {
    attrs.overrideClasses.forEach((cls, index) => { if (cls !== null) overrides[attrs.ids[index]] = cls; });
  }
  return {
    threshold: source.threshold, unknownThreshold: source.unknownThreshold, overrides,
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

export function reviewRows(attrs, classification, filter) {
  return attrs.ids.map((_id, index) => index).filter((index) =>
    filter === "all" || classification.classes[index] === filter,
  );
}

export function nextReviewIndex(rows, current, direction) {
  if (!rows.length) return null;
  const position = rows.indexOf(current);
  if (position >= 0) return rows[(position + direction + rows.length) % rows.length];
  if (direction > 0) return rows.find((row) => row > current) ?? rows[0];
  for (let index = rows.length - 1; index >= 0; index--) {
    if (rows[index] < current) return rows[index];
  }
  return rows[rows.length - 1];
}

export function reviewLocation(data, id, overtureId) {
  const feature = data?.features?.length === 1 ? data.features[0] : null;
  const coordinates = feature?.geometry?.coordinates;
  if (feature?.properties?.rowId !== id || feature?.properties?.id !== overtureId ||
      feature?.geometry?.type !== "Point" || !Array.isArray(coordinates) ||
      coordinates.length !== 2 || !coordinates.every(Number.isFinite) ||
      Math.abs(coordinates[0]) > 180 || Math.abs(coordinates[1]) > 90) {
    throw new Error("The building location does not match these predictions.");
  }
  return coordinates;
}
