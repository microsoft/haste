// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

// Pure helpers for reconciling the Interactive Labeler's two views of a
// label set:
//
//   * the SAVED set, keyed by Overture id, as returned by
//     GetInteractiveLabels and mirrored in savedLabelsRef;
//   * the SESSION set, keyed by the sidecar's row index, held in
//     labeledMapRef along with each building's feature vector.
//
// Those id spaces only meet on a rendered vector tile, which is why the
// labeler used to discover its own labels as the user panned. These helpers
// keep the reconciliation logic out of the component so it can be tested
// directly.

// Extension included so `node --test` can resolve this the same way Vite does.
import {
  CLASS_CLOUDY,
  CLASS_DAMAGED,
  CLASS_INTACT,
} from "./interactiveModel.js";

// In-browser class <-> validation-report vocabulary (Damaged/NotDamaged/
// Unknown). The persisted store speaks the validation vocabulary so the
// interactive labels stay readable alongside the Building Validation ones.
export const CLASS_TO_VALIDATION = {
  [CLASS_INTACT]: "NotDamaged",
  [CLASS_DAMAGED]: "Damaged",
  [CLASS_CLOUDY]: "Unknown",
};
export const VALIDATION_TO_CLASS = {
  NotDamaged: CLASS_INTACT,
  Damaged: CLASS_DAMAGED,
  Unknown: CLASS_CLOUDY,
};

/**
 * Build the complete label document to PUT.
 *
 * PutInteractiveLabels REPLACES the stored document, so the payload must be
 * the whole set. Sending only the session's labels destroys every saved
 * label whose tile never rendered — the data loss in
 * github.com/microsoft/haste/issues/113. Saved entries are carried through
 * untouched (keeping their original updatedAt) and the session's labels are
 * layered on top.
 *
 * @param {object} saved - savedLabelsRef contents, keyed by Overture id.
 * @param {object} labeled - labeledMapRef contents, keyed by row index.
 * @param {string} savedAt - ISO timestamp for entries written by this save.
 * @param {number|null} sidecarSize - Building count of the sidecar these row
 *   indices were resolved against, stamped alongside them so a later session
 *   can tell whether they still apply.
 * @returns {object} The merged label document, keyed by Overture id.
 */
export function mergeLabelsForSave(saved, labeled, savedAt, sidecarSize) {
  const labels = {};

  for (const [overtureId, entry] of Object.entries(saved || {})) {
    // Skip anything we can't interpret rather than echoing it back.
    if (entry && VALIDATION_TO_CLASS[entry.label] != null) {
      labels[overtureId] = entry;
    }
  }

  for (const [rowId, entry] of Object.entries(labeled || {})) {
    const overtureId = entry.overtureId ?? rowId;
    labels[overtureId] = {
      id: overtureId,
      // Row index into this model's features sidecar. Persisting it is what
      // lets the next session restore every label up front instead of
      // waiting for tiles. Overture id stays the key because it is what
      // survives a re-embed.
      rowId: Number(rowId),
      // Fingerprint for the above. Row indices are only meaningful against
      // the sidecar that produced them; if a model is re-embedded the
      // numbering can shift, and a stale index would silently point at a
      // different building. Recording the building count lets the next
      // session tell whether the index still applies.
      n: sidecarSize ?? null,
      label: CLASS_TO_VALIDATION[entry.label],
      updatedAt: savedAt,
    };
  }

  return labels;
}

/**
 * Pick the saved labels that can be restored immediately, before any tile
 * has rendered.
 *
 * Only entries carrying a rowId qualify; anything saved before rowId existed
 * still has to wait for its tile, since nothing else bridges Overture id to
 * row index on the client.
 *
 * A row index is only trusted when it carries a fingerprint matching the
 * sidecar now loaded. Without that check a re-embed could leave an index
 * pointing at a different building, and the restored entry would be used for
 * training and Predict All long before any tile rendered to correct it.
 * Unverifiable entries fall back to the tile-driven path, which reads the
 * Overture id off the tile itself and cannot be wrong.
 *
 * @param {object} saved - savedLabelsRef contents, keyed by Overture id.
 * @param {object} labeled - already-restored entries, keyed by row index.
 * @param {number|null} sidecarSize - Building count of the loaded sidecar.
 * @returns {{candidates: Array<{rowId: number, cls: number, overtureId: string}>, legacy: number}}
 *   `candidates` are ready to place; `legacy` counts entries that must wait.
 */
export function selectRestorableByRowId(saved, labeled, sidecarSize) {
  const candidates = [];
  let legacy = 0;

  for (const [overtureId, entry] of Object.entries(saved || {})) {
    const rowId = entry?.rowId;
    if (typeof rowId !== "number" || !Number.isInteger(rowId) || rowId < 0) {
      legacy++;
      continue;
    }
    // No fingerprint, or one from a different sidecar: cannot vouch for it.
    if (
      sidecarSize == null ||
      typeof entry.n !== "number" ||
      entry.n !== sidecarSize
    ) {
      legacy++;
      continue;
    }
    if (labeled && labeled[rowId]) continue;
    const cls = VALIDATION_TO_CLASS[entry.label];
    if (cls == null) continue;
    candidates.push({ rowId, cls, overtureId });
  }

  return { candidates, legacy };
}

/**
 * Tally labels for the panel and for the trainability gate.
 *
 * These differ: `counts` is everything the user has labeled, including saved
 * labels not yet bridged to a row index, so the panel doesn't read 0 on load.
 * `trainable` is the subset backed by a usable feature vector, which is all
 * the in-browser model can fit — gating the Predicted view on `counts` would
 * enable a toggle that then reports "need more labels".
 *
 * @param {object} labeled - labeledMapRef contents, keyed by row index.
 * @param {object} saved - savedLabelsRef contents, keyed by Overture id.
 * @param {(vec: unknown) => boolean} isValidVector - feature-vector predicate.
 * @returns {{counts: object, trainable: object}} Both keyed by class.
 */
export function tallyLabels(labeled, saved, isValidVector) {
  const counts = { [CLASS_INTACT]: 0, [CLASS_DAMAGED]: 0, [CLASS_CLOUDY]: 0 };
  const trainable = {
    [CLASS_INTACT]: 0,
    [CLASS_DAMAGED]: 0,
    [CLASS_CLOUDY]: 0,
  };
  const placed = new Set();

  for (const entry of Object.values(labeled || {})) {
    if (counts[entry.label] == null) continue;
    counts[entry.label] += 1;
    if (isValidVector(entry.features)) trainable[entry.label] += 1;
    if (entry.overtureId != null) placed.add(String(entry.overtureId));
  }

  for (const [overtureId, entry] of Object.entries(saved || {})) {
    if (placed.has(String(overtureId))) continue;
    const cls = VALIDATION_TO_CLASS[entry?.label];
    if (cls == null) continue;
    counts[cls] += 1;
  }

  return { counts, trainable };
}
