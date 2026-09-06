// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Read-only subset of PR136's columnar prediction helpers. Classes are
// authoritative, including for RAW predictions; their presence says nothing
// about whether an analyst edited the output.
export const CLASS_DAMAGED = "Damaged";
export const CLASS_NOT_DAMAGED = "NotDamaged";
export const CLASS_UNKNOWN = "Unknown";
export const PREDICTION_CLASSES = [
  CLASS_DAMAGED, CLASS_NOT_DAMAGED, CLASS_UNKNOWN,
];
export const CLASS_LABELS = {
  [CLASS_DAMAGED]: "Damaged",
  [CLASS_NOT_DAMAGED]: "Not Damaged",
  [CLASS_UNKNOWN]: "Unknown",
};

const COLUMNS = [
  "ids", "overtureIds", "damage", "unknown", "damaged", "classes",
];
const isScore = (value) =>
  value === null ||
  (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1);

/** Fail closed: a bad row must never be silently painted as NotDamaged. */
export function normalizeAttrs(raw, expected) {
  const invalid = (detail) => {
    throw new Error(`Invalid prediction attributes: ${detail}.`);
  };
  if (raw?.schemaVersion !== 1) invalid("unsupported schema version");
  if (!["inference", "embedding"].includes(raw.flavor)) invalid("unknown flavor");
  if (typeof raw.predictionRevision !== "string" || !raw.predictionRevision.trim()) {
    invalid("missing prediction revision");
  }
  if (!Number.isSafeInteger(raw.n) || raw.n < 0) invalid("invalid row count");
  for (const column of COLUMNS) {
    if (!Array.isArray(raw[column]) || raw[column].length !== raw.n) {
      invalid(`${column} must contain exactly ${raw.n} rows`);
    }
  }
  if (expected) {
    if (raw.n !== expected.buildingCount) invalid("result and sidecar counts differ");
    if (raw.flavor !== expected.flavor) invalid("result and sidecar flavors differ");
    if (raw.predictionRevision !== expected.predictionRevision) {
      invalid("result and sidecar revisions differ; refresh results");
    }
  }
  const seen = new Set();
  for (let i = 0; i < raw.n; i++) {
    const id = raw.ids[i];
    if (!Number.isSafeInteger(id) || id < 0 || id >= raw.n || seen.has(id)) {
      invalid("source IDs must be unique and contiguous from zero");
    }
    seen.add(id);
    if (typeof raw.overtureIds[i] !== "string" || !raw.overtureIds[i].trim()) {
      invalid(`missing Overture identity at row ${i}`);
    }
    if (!isScore(raw.damage[i]) || !isScore(raw.unknown[i])) {
      invalid(`invalid score at row ${i}`);
    }
    if (![0, 1, null].includes(raw.damaged[i])) invalid(`invalid damaged flag at row ${i}`);
    if (!PREDICTION_CLASSES.includes(raw.classes[i])) invalid(`invalid class at row ${i}`);
    if (
      (raw.damage[i] === null || raw.unknown[i] === null) &&
      raw.classes[i] !== CLASS_UNKNOWN
    ) {
      invalid(`unscored row ${i} must be Unknown`);
    }
  }
  return raw;
}

export function indexById(attrs) {
  return new Map(attrs.ids.map((id, index) => [id, index]));
}

export function classifyAll(attrs) {
  const counts = Object.fromEntries(PREDICTION_CLASSES.map((cls) => [cls, 0]));
  for (const cls of attrs.classes) counts[cls]++;
  return { classes: attrs.classes, counts, total: attrs.n };
}
