// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Pure classification helpers for the Prediction Editor.
//
// Everything the editor needs to decide "what class is this building right
// now?" lives here as plain functions over plain data: no React, no Azure
// Maps, no fetch. The component keeps the attribute arrays in a ref and the
// override map in state, then calls into this module — which makes the
// interesting logic (threshold derivation, override merging, filtering, and
// the "how many buildings would flip" counter) unit-testable with
// `node --test`.
//
// IMPORTANT: `damage` and `unknown` are FRACTIONS in [0, 1] as produced by
// the model, NOT 0-100 percentages. All threshold arithmetic here stays in
// [0, 1]; percentages are a display concern (see toPercentLabel).

export const CLASS_DAMAGED = "Damaged";
export const CLASS_NOT_DAMAGED = "NotDamaged";
export const CLASS_UNKNOWN = "Unknown";

// Cycle order used when the user clicks a footprint in "cycle" mode.
export const PREDICTION_CLASSES = [
  CLASS_DAMAGED,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
];

export const FILTER_ALL = "all";
export const FILTER_EDITED = "edited";

// Order matters — this drives the right panel's filter dropdown.
export const FILTER_VALUES = [
  FILTER_ALL,
  CLASS_DAMAGED,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
  FILTER_EDITED,
];

export const FILTER_LABELS = {
  [FILTER_ALL]: "All buildings",
  [CLASS_DAMAGED]: "Damaged only",
  [CLASS_NOT_DAMAGED]: "Not Damaged only",
  [CLASS_UNKNOWN]: "Unknown only",
  [FILTER_EDITED]: "Edited only",
};

export const CLASS_LABELS = {
  [CLASS_DAMAGED]: "Damaged",
  [CLASS_NOT_DAMAGED]: "Not Damaged",
  [CLASS_UNKNOWN]: "Unknown",
};

// Non-finite scores (missing rows, NaN placeholders) are treated as 0 so a
// corrupt entry degrades to "NotDamaged" rather than throwing mid-render.
function num(value, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

/** True when `value` is one of the three prediction classes. */
export function isPredictionClass(value) {
  return PREDICTION_CLASSES.indexOf(value) !== -1;
}

/**
 * The model's class for one building, before any user edit.
 *
 *   Unknown     when unknown > unknownThreshold
 *   Damaged     when damage  > threshold
 *   NotDamaged  otherwise
 *
 * Both comparisons are strict so the default unknownThreshold of 0 means
 * "any non-zero unknown score wins", and a threshold of 1 can never produce
 * a Damaged building.
 */
export function deriveClass(damage, unknown, threshold, unknownThreshold = 0) {
  if (num(unknown) > num(unknownThreshold)) return CLASS_UNKNOWN;
  if (num(damage) > num(threshold)) return CLASS_DAMAGED;
  return CLASS_NOT_DAMAGED;
}

/**
 * Coerce the raw prediction_attrs sidecar into the shape the editor uses.
 * Missing arrays become empty ones and `n` is clamped to the shortest array
 * actually present, so a truncated sidecar can't index past its data.
 */
export function normalizeAttrs(raw) {
  const ids = Array.isArray(raw?.ids) ? raw.ids : [];
  const overtureIds = Array.isArray(raw?.overtureIds) ? raw.overtureIds : [];
  const damage = Array.isArray(raw?.damage) ? raw.damage : [];
  const unknown = Array.isArray(raw?.unknown) ? raw.unknown : [];
  const damaged = Array.isArray(raw?.damaged) ? raw.damaged : [];
  const declared = num(raw?.n, ids.length);
  const n = Math.max(0, Math.min(declared, ids.length));
  return { n, ids, overtureIds, damage, unknown, damaged };
}

/** Map of building id -> row index, for turning a clicked feature id into attrs. */
export function indexById(attrs) {
  const map = new Map();
  const n = attrs?.n || 0;
  for (let i = 0; i < n; i++) {
    map.set(attrs.ids[i], i);
  }
  return map;
}

// ── Override map ────────────────────────────────────────────────────────────
// Overrides are a sparse plain object keyed by building id. It is stored in
// React state, so every mutator below returns a NEW object rather than
// editing in place.

/** The user's class for `id`, or null when they haven't edited it. */
export function getOverride(overrides, id) {
  if (!overrides || id == null) return null;
  const value = overrides[id];
  return isPredictionClass(value) ? value : null;
}

/** Set one override. Invalid classes are ignored (returns the input map). */
export function setOverride(overrides, id, cls) {
  return setOverrides(overrides, [id], cls);
}

/** Set many overrides at once — the ctrl+drag box-select path. */
export function setOverrides(overrides, ids, cls) {
  if (!isPredictionClass(cls) || !Array.isArray(ids) || ids.length === 0) {
    return overrides || {};
  }
  const next = { ...(overrides || {}) };
  let changed = false;
  for (const id of ids) {
    if (id == null) continue;
    if (next[id] === cls) continue;
    next[id] = cls;
    changed = true;
  }
  return changed ? next : overrides || {};
}

/**
 * Apply a batch of per-building classes in one immutable update:
 * `entries` is `[{ id, class }]`. Box-selecting in cycle mode gives every
 * building a different target class, and merging them one at a time would
 * copy the whole map per building.
 */
export function setOverrideEntries(overrides, entries) {
  if (!Array.isArray(entries) || entries.length === 0) return overrides || {};
  const next = { ...(overrides || {}) };
  let changed = false;
  for (const entry of entries) {
    const id = entry?.id;
    const cls = entry?.class;
    if (id == null || !isPredictionClass(cls)) continue;
    if (next[id] === cls) continue;
    next[id] = cls;
    changed = true;
  }
  return changed ? next : overrides || {};
}

/** Drop one override so the building falls back to its derived class. */
export function clearOverride(overrides, id) {
  return clearOverrides(overrides, [id]);
}
/** Drop many overrides at once. */
export function clearOverrides(overrides, ids) {
  if (!overrides || !Array.isArray(ids) || ids.length === 0) {
    return overrides || {};
  }
  const next = { ...overrides };
  let changed = false;
  for (const id of ids) {
    if (id == null) continue;
    if (Object.prototype.hasOwnProperty.call(next, id)) {
      delete next[id];
      changed = true;
    }
  }
  return changed ? next : overrides;
}

/** How many buildings the user has edited. */
export function countOverrides(overrides) {
  return Object.keys(overrides || {}).length;
}

/**
 * The sparse override list sent to PutEditedPredictions:
 * `[{ id, class }]`, numerically sorted so repeated saves of the same edits
 * produce a byte-identical payload.
 */
export function toOverrideList(overrides) {
  return Object.keys(overrides || {})
    .filter((key) => isPredictionClass(overrides[key]))
    .map((key) => ({ id: Number(key), class: overrides[key] }))
    .sort((a, b) => a.id - b.id);
}

/** The exact PUT body for PutEditedPredictions. */
export function buildSavePayload({
  projectId,
  imageLayerId,
  modelId,
  threshold,
  unknownThreshold,
  overrides,
}) {
  return {
    projectId,
    imageLayerId,
    modelId,
    threshold: num(threshold),
    unknownThreshold: num(unknownThreshold),
    overrides: toOverrideList(overrides),
  };
}

// ── Classification over the whole layer ─────────────────────────────────────

/** The current class of row `index`: the user's edit if any, else derived. */
export function resolveClassAt(attrs, index, options) {
  const { threshold = 0.5, unknownThreshold = 0, overrides = null } =
    options || {};
  const override = getOverride(overrides, attrs?.ids?.[index]);
  if (override) return override;
  return deriveClass(
    attrs?.damage?.[index],
    attrs?.unknown?.[index],
    threshold,
    unknownThreshold
  );
}

/**
 * Classify every building once. Returns parallel arrays (cheap to index from
 * the map's feature-state writer) plus the per-class counts the right panel
 * shows. `edited[i]` is true when the class came from a user override.
 */
export function classifyAll(attrs, options) {
  const { threshold = 0.5, unknownThreshold = 0, overrides = null } =
    options || {};
  const n = attrs?.n || 0;
  const classes = new Array(n);
  const edited = new Array(n);
  const counts = {
    [CLASS_DAMAGED]: 0,
    [CLASS_NOT_DAMAGED]: 0,
    [CLASS_UNKNOWN]: 0,
  };
  let editedCount = 0;
  for (let i = 0; i < n; i++) {
    const override = getOverride(overrides, attrs.ids[i]);
    const cls =
      override ||
      deriveClass(
        attrs.damage[i],
        attrs.unknown[i],
        threshold,
        unknownThreshold
      );
    classes[i] = cls;
    edited[i] = override != null;
    if (override != null) editedCount++;
    counts[cls] = (counts[cls] || 0) + 1;
  }
  return { classes, edited, counts, editedCount, total: n };
}

/** Filter predicate shared by the map dimming and the traversal list. */
export function matchesFilter(cls, isEdited, filter) {
  if (!filter || filter === FILTER_ALL) return true;
  if (filter === FILTER_EDITED) return !!isEdited;
  return cls === filter;
}

/** Row indices that pass `filter`, in ascending order. */
export function filterIndices(classification, filter) {
  const classes = classification?.classes || [];
  const edited = classification?.edited || [];
  if (!filter || filter === FILTER_ALL) {
    return classes.map((_cls, i) => i);
  }
  const out = [];
  for (let i = 0; i < classes.length; i++) {
    if (matchesFilter(classes[i], edited[i], filter)) out.push(i);
  }
  return out;
}

/**
 * How many buildings would change class when moving from one threshold
 * setting to another. Buildings the user has explicitly edited are excluded:
 * their class is pinned by the override, so a slider move can never flip
 * them. This is what drives the live "N buildings would change class"
 * readout — no server round-trip involved.
 */
export function countClassChanges(attrs, baseline, candidate, overrides = null) {
  const n = attrs?.n || 0;
  const fromT = num(baseline?.threshold, 0.5);
  const fromU = num(baseline?.unknownThreshold, 0);
  const toT = num(candidate?.threshold, 0.5);
  const toU = num(candidate?.unknownThreshold, 0);
  if (fromT === toT && fromU === toU) return 0;
  let changed = 0;
  for (let i = 0; i < n; i++) {
    if (getOverride(overrides, attrs.ids[i])) continue;
    const before = deriveClass(attrs.damage[i], attrs.unknown[i], fromT, fromU);
    const after = deriveClass(attrs.damage[i], attrs.unknown[i], toT, toU);
    if (before !== after) changed++;
  }
  return changed;
}

/** The next class in the cycle order (used by plain left-click). */
export function cycleClass(cls) {
  const pos = PREDICTION_CLASSES.indexOf(cls);
  if (pos === -1) return PREDICTION_CLASSES[0];
  return PREDICTION_CLASSES[(pos + 1) % PREDICTION_CLASSES.length];
}

// ── Traversal ───────────────────────────────────────────────────────────────

// Position of the last entry strictly below `value` (-1 when there is none).
function positionBefore(list, value) {
  let pos = -1;
  for (let i = 0; i < list.length; i++) {
    if (list[i] < value) pos = i;
    else break;
  }
  return pos;
}

// Position of the first entry strictly above `value` (list.length when none).
function positionAfter(list, value) {
  for (let i = 0; i < list.length; i++) {
    if (list[i] > value) return i;
  }
  return list.length;
}

/**
 * Walk an ascending list of row indices cyclically.
 *
 * `isCandidate` is optional: when supplied, the walk returns the first entry
 * that satisfies it (the editor uses this to prefer buildings whose geometry
 * has already streamed in, so Next actually pans somewhere). If nothing
 * satisfies the predicate we fall back to the plain next entry rather than
 * refusing to move. Returns null for an empty list.
 */
export function nextIndexInList(
  list,
  fromIndex,
  direction = 1,
  isCandidate = null
) {
  if (!Array.isArray(list) || list.length === 0) return null;
  const step = direction < 0 ? -1 : 1;
  const n = list.length;
  let start = list.indexOf(fromIndex);
  if (start === -1) {
    // The selection isn't in the filtered list (it was filtered out, or
    // nothing is selected yet). Start from the insertion point so the first
    // step lands on the nearest neighbour in the direction of travel.
    start = step > 0 ? positionBefore(list, fromIndex) : positionAfter(list, fromIndex);
  }
  let fallback = null;
  for (let k = 1; k <= n; k++) {
    const pos = (((start + k * step) % n) + n) % n;
    const value = list[pos];
    if (fallback === null) fallback = value;
    if (!isCandidate || isCandidate(value)) return value;
  }
  return fallback;
}

// ── Version helpers ─────────────────────────────────────────────────────────

/** The highest-numbered saved version, or null when there are none. */
export function latestVersion(versions) {
  if (!Array.isArray(versions) || versions.length === 0) return null;
  return versions.reduce((best, v) =>
    num(v?.version, -Infinity) > num(best?.version, -Infinity) ? v : best
  );
}

/** Versions newest-first, for the right panel's history list. */
export function sortVersionsDescending(versions) {
  if (!Array.isArray(versions)) return [];
  return [...versions].sort((a, b) => num(b?.version) - num(a?.version));
}

// ── Display helpers ─────────────────────────────────────────────────────────

/** Render a [0, 1] fraction as a percentage string. */
export function toPercentLabel(fraction, digits = 0) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}
