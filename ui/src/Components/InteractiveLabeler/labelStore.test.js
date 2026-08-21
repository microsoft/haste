// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

// Tests for the Interactive Labeler's label reconciliation.
//
// The defect these guard against (issue #113) is that the saved set and the
// session set live in different id spaces, bridged only by a rendered vector
// tile. Two consequences: the panel reported 0 labels until the user panned
// over them, and saving from that state replaced the full stored set with
// whatever happened to be hydrated — one report went from 1,311 labels to 552.
//
// Run: node --test ui/src/Components/InteractiveLabeler/labelStore.test.js

import assert from "node:assert/strict";
import test from "node:test";

import {
  CLASS_TO_VALIDATION,
  VALIDATION_TO_CLASS,
  mergeLabelsForSave,
  selectRestorableByRowId,
  tallyLabels,
} from "./labelStore.js";
import {
  CLASS_CLOUDY,
  CLASS_DAMAGED,
  CLASS_INTACT,
} from "./interactiveModel.js";

const AT = "2026-08-21T00:00:00.000Z";

// A saved-store entry as GetInteractiveLabels returns it.
function savedEntry(overtureId, label, rowId) {
  const entry = { id: overtureId, label, updatedAt: "2026-08-01T00:00:00Z" };
  if (rowId !== undefined) entry.rowId = rowId;
  return entry;
}

// A labeledMapRef entry: keyed by row index, carrying the feature vector.
function sessionEntry(label, overtureId, features = new Float32Array([1, 2])) {
  return { label, overtureId, features };
}

const isValidVector = (v) => !!v && v.every((x) => x != null && !Number.isNaN(x));

test("class vocabularies round-trip", () => {
  for (const cls of [CLASS_INTACT, CLASS_DAMAGED, CLASS_CLOUDY]) {
    assert.equal(VALIDATION_TO_CLASS[CLASS_TO_VALIDATION[cls]], cls);
  }
});

// ── mergeLabelsForSave ──────────────────────────────────────────────────────

test("merge preserves saved labels the session never hydrated", () => {
  // The #113 scenario: 3 labels on the server, only 1 bridged to a row index.
  const saved = {
    a: savedEntry("a", "Damaged", 10),
    b: savedEntry("b", "NotDamaged", 11),
    c: savedEntry("c", "Unknown", 12),
  };
  const labeled = { 10: sessionEntry(CLASS_DAMAGED, "a") };

  const out = mergeLabelsForSave(saved, labeled, AT);

  assert.deepEqual(Object.keys(out).sort(), ["a", "b", "c"]);
  // Untouched entries keep their original timestamp.
  assert.equal(out.b.updatedAt, "2026-08-01T00:00:00Z");
  assert.equal(out.c.label, "Unknown");
});

test("merge does not shrink the stored set when nothing is hydrated", () => {
  const saved = {};
  for (let i = 0; i < 1311; i++) {
    saved[`o${i}`] = savedEntry(`o${i}`, i % 2 ? "Damaged" : "NotDamaged", i);
  }

  const out = mergeLabelsForSave(saved, {}, AT);

  assert.equal(Object.keys(out).length, 1311);
});

test("session labels win over the saved copy", () => {
  const saved = { a: savedEntry("a", "NotDamaged", 10) };
  const labeled = { 10: sessionEntry(CLASS_DAMAGED, "a") };

  const out = mergeLabelsForSave(saved, labeled, AT);

  assert.equal(Object.keys(out).length, 1);
  assert.equal(out.a.label, "Damaged");
  assert.equal(out.a.updatedAt, AT);
});

test("merge stamps rowId so the next session can restore up front", () => {
  const labeled = { 42: sessionEntry(CLASS_DAMAGED, "abc") };

  const out = mergeLabelsForSave({}, labeled, AT);

  assert.equal(out.abc.rowId, 42);
  assert.equal(typeof out.abc.rowId, "number");
});

test("merge falls back to the row index when there is no Overture id", () => {
  const labeled = { 7: { label: CLASS_INTACT, features: null } };

  const out = mergeLabelsForSave({}, labeled, AT);

  assert.equal(out["7"].id, "7");
  assert.equal(out["7"].rowId, 7);
});

test("merge drops saved entries with an unrecognized label", () => {
  const saved = {
    good: savedEntry("good", "Damaged", 1),
    bad: savedEntry("bad", "Sideways", 2),
  };

  const out = mergeLabelsForSave(saved, {}, AT);

  assert.deepEqual(Object.keys(out), ["good"]);
});

test("a cleared label stays cleared", () => {
  // clearLabel removes from BOTH maps; the merge must not resurrect it.
  const saved = { a: savedEntry("a", "Damaged", 10) };
  delete saved.a;

  const out = mergeLabelsForSave(saved, {}, AT);

  assert.deepEqual(Object.keys(out), []);
});

test("merge tolerates empty and missing inputs", () => {
  assert.deepEqual(mergeLabelsForSave(undefined, undefined, AT), {});
  assert.deepEqual(mergeLabelsForSave({}, {}, AT), {});
});

// ── selectRestorableByRowId ─────────────────────────────────────────────────

test("labels with a rowId restore without waiting for tiles", () => {
  const saved = {
    a: savedEntry("a", "Damaged", 10),
    b: savedEntry("b", "NotDamaged", 11),
  };

  const { candidates, legacy } = selectRestorableByRowId(saved, {});

  assert.equal(candidates.length, 2);
  assert.equal(legacy, 0);
  assert.deepEqual(
    candidates.map((c) => c.rowId).sort((x, y) => x - y),
    [10, 11]
  );
  assert.equal(candidates.find((c) => c.rowId === 10).cls, CLASS_DAMAGED);
});

test("labels saved before rowId existed are reported as legacy", () => {
  const saved = {
    a: savedEntry("a", "Damaged"),
    b: savedEntry("b", "NotDamaged"),
    c: savedEntry("c", "Damaged", 12),
  };

  const { candidates, legacy } = selectRestorableByRowId(saved, {});

  assert.equal(candidates.length, 1);
  assert.equal(legacy, 2);
});

test("already-restored rows are not re-restored", () => {
  const saved = { a: savedEntry("a", "Damaged", 10) };
  const labeled = { 10: sessionEntry(CLASS_DAMAGED, "a") };

  const { candidates } = selectRestorableByRowId(saved, labeled);

  assert.equal(candidates.length, 0);
});

test("malformed rowIds are treated as legacy, not trusted", () => {
  const saved = {
    str: { id: "str", label: "Damaged", rowId: "10" },
    frac: { id: "frac", label: "Damaged", rowId: 1.5 },
    neg: { id: "neg", label: "Damaged", rowId: -1 },
    nan: { id: "nan", label: "Damaged", rowId: Number.NaN },
  };

  const { candidates, legacy } = selectRestorableByRowId(saved, {});

  assert.equal(candidates.length, 0);
  assert.equal(legacy, 4);
});

test("rowId 0 is a valid row, not a missing one", () => {
  const saved = { a: savedEntry("a", "Damaged", 0) };

  const { candidates, legacy } = selectRestorableByRowId(saved, {});

  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].rowId, 0);
  assert.equal(legacy, 0);
});

// ── tallyLabels ─────────────────────────────────────────────────────────────

test("counts include saved labels that are not yet bridged", () => {
  // This is the "panel shows 0" symptom: nothing hydrated, 3 on the server.
  const saved = {
    a: savedEntry("a", "Damaged", 10),
    b: savedEntry("b", "NotDamaged", 11),
    c: savedEntry("c", "Unknown", 12),
  };

  const { counts, trainable } = tallyLabels({}, saved, isValidVector);

  assert.equal(counts[CLASS_DAMAGED], 1);
  assert.equal(counts[CLASS_INTACT], 1);
  assert.equal(counts[CLASS_CLOUDY], 1);
  // None can train yet — no feature vectors.
  assert.equal(trainable[CLASS_DAMAGED], 0);
});

test("a label present in both maps is counted once", () => {
  const saved = { a: savedEntry("a", "Damaged", 10) };
  const labeled = { 10: sessionEntry(CLASS_DAMAGED, "a") };

  const { counts, trainable } = tallyLabels(labeled, saved, isValidVector);

  assert.equal(counts[CLASS_DAMAGED], 1);
  assert.equal(trainable[CLASS_DAMAGED], 1);
});

test("trainable excludes entries whose feature vector is unusable", () => {
  const labeled = {
    10: sessionEntry(CLASS_DAMAGED, "a"),
    11: sessionEntry(CLASS_DAMAGED, "b", new Float32Array([Number.NaN, 1])),
  };

  const { counts, trainable } = tallyLabels(labeled, {}, isValidVector);

  assert.equal(counts[CLASS_DAMAGED], 2);
  assert.equal(trainable[CLASS_DAMAGED], 1);
});

test("counts and trainable agree once everything is hydrated", () => {
  const saved = {
    a: savedEntry("a", "Damaged", 10),
    b: savedEntry("b", "NotDamaged", 11),
  };
  const labeled = {
    10: sessionEntry(CLASS_DAMAGED, "a"),
    11: sessionEntry(CLASS_INTACT, "b"),
  };

  const { counts, trainable } = tallyLabels(labeled, saved, isValidVector);

  assert.deepEqual(counts, trainable);
});

test("numeric and string Overture ids match rather than double-count", () => {
  // JSON object keys are strings; a session entry may carry a number.
  const saved = { 42: savedEntry(42, "Damaged", 42) };
  const labeled = { 42: sessionEntry(CLASS_DAMAGED, 42) };

  const { counts } = tallyLabels(labeled, saved, isValidVector);

  assert.equal(counts[CLASS_DAMAGED], 1);
});

test("tally tolerates empty and missing inputs", () => {
  const { counts, trainable } = tallyLabels(undefined, undefined, isValidVector);
  assert.deepEqual(counts, {
    [CLASS_INTACT]: 0,
    [CLASS_DAMAGED]: 0,
    [CLASS_CLOUDY]: 0,
  });
  assert.deepEqual(trainable, counts);
});
