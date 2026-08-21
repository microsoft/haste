// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Run with: node --test src/Components/PredictionEditor/predictionClassify.test.js

import test from "node:test";
import assert from "node:assert/strict";

import {
  CLASS_DAMAGED,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
  FILTER_ALL,
  FILTER_EDITED,
  buildSavePayload,
  classifyAll,
  clearOverride,
  countClassChanges,
  countOverrides,
  cycleClass,
  deriveClass,
  filterIndices,
  getOverride,
  indexById,
  latestVersion,
  matchesFilter,
  nextIndexInList,
  normalizeAttrs,
  resolveClassAt,
  setOverride,
  setOverrideEntries,
  setOverrides,
  sortVersionsDescending,
  toOverrideList,
  toPercentLabel,
} from "./predictionClassify.js";
import {
  MAX_PREP_POLL_ATTEMPTS,
  PREP_PHASE_FAILED,
  PREP_PHASE_READY,
  PREP_PHASE_TIMED_OUT,
  PREP_PHASE_WAITING,
  PREP_POLL_INTERVAL_MS,
  PREP_STATUS_CANCELLED,
  PREP_STATUS_FAILED,
  PREP_STATUS_IN_PROGRESS,
  PREP_STATUS_QUEUED,
  applyPrepResponse,
  buildPrepRequest,
  describeOutstandingArtifacts,
  evaluatePrepState,
  isPrepReady,
  isTerminalPrepStatus,
  nextPollAttempt,
  normalizePrepStatus,
  prepStateAfterPollError,
  prepStatusLabel,
  shouldPollPrep,
} from "./predictionPrep.js";
import {
  SWIPE_MODE_BASEMAP_POST,
  SWIPE_MODE_NONE,
  SWIPE_MODE_PRE_POST,
  dividerPositionForKey,
  isSwipeAvailable,
  resolveSwipeMode,
  swipeComparisonTileUrl,
  swipeLeftPaneLabel,
  swipeModeHint,
  swipeRightPaneLabel,
  swipeToggleLabel,
} from "./predictionSwipe.js";

// Five buildings covering every interesting corner: below/at/above the
// threshold, and one with a non-zero unknown score.
function sampleAttrs() {
  return normalizeAttrs({
    n: 5,
    ids: [10, 11, 12, 13, 14],
    overtureIds: ["a", "b", "c", "d", "e"],
    damage: [0.05, 0.5, 0.51, 0.9, 0.8],
    unknown: [0, 0, 0, 0, 0.4],
    damaged: [0, 0, 1, 1, 0],
  });
}

test("deriveClass thresholds on fractions, not percentages", () => {
  assert.equal(deriveClass(0.9, 0, 0.5), CLASS_DAMAGED);
  assert.equal(deriveClass(0.1, 0, 0.5), CLASS_NOT_DAMAGED);
  // Strictly greater: a score exactly at the threshold is not damaged.
  assert.equal(deriveClass(0.5, 0, 0.5), CLASS_NOT_DAMAGED);
  // A 0-100 style value would be nonsense here; 90 > 0.5 is still damaged,
  // which is exactly why the caller must pass fractions.
  assert.equal(deriveClass(0.5001, 0, 0.5), CLASS_DAMAGED);
});

test("deriveClass gives the unknown score priority over damage", () => {
  // Default unknownThreshold of 0: any positive unknown wins.
  assert.equal(deriveClass(0.99, 0.01, 0.5), CLASS_UNKNOWN);
  assert.equal(deriveClass(0.99, 0, 0.5), CLASS_DAMAGED);
  // Raising the unknown threshold lets the damage score through again.
  assert.equal(deriveClass(0.99, 0.4, 0.5, 0.5), CLASS_DAMAGED);
  assert.equal(deriveClass(0.99, 0.6, 0.5, 0.5), CLASS_UNKNOWN);
});

test("deriveClass treats non-finite scores as zero", () => {
  assert.equal(deriveClass(NaN, undefined, 0.5), CLASS_NOT_DAMAGED);
  assert.equal(deriveClass(null, null, 0.5), CLASS_NOT_DAMAGED);
});

test("normalizeAttrs clamps n to the data actually present", () => {
  const attrs = normalizeAttrs({ n: 99, ids: [1, 2] });
  assert.equal(attrs.n, 2);
  assert.deepEqual(attrs.damage, []);

  const empty = normalizeAttrs(undefined);
  assert.equal(empty.n, 0);
  assert.deepEqual(empty.ids, []);
});

test("indexById maps feature ids back to attribute rows", () => {
  const map = indexById(sampleAttrs());
  assert.equal(map.get(10), 0);
  assert.equal(map.get(14), 4);
  assert.equal(map.get(999), undefined);
});

test("override merging is immutable and drops no-op writes", () => {
  const empty = {};
  const one = setOverride(empty, 12, CLASS_UNKNOWN);
  assert.deepEqual(empty, {}, "input map must not be mutated");
  assert.equal(getOverride(one, 12), CLASS_UNKNOWN);

  // Writing the same value again returns the identical object so React can
  // skip the re-render.
  assert.equal(setOverride(one, 12, CLASS_UNKNOWN), one);

  // Invalid classes are ignored.
  assert.equal(setOverride(one, 13, "Rubble"), one);
  assert.equal(getOverride(one, 13), null);

  const many = setOverrides(one, [10, 11], CLASS_DAMAGED);
  assert.equal(countOverrides(many), 3);

  const cleared = clearOverride(many, 12);
  assert.equal(getOverride(cleared, 12), null);
  assert.equal(countOverrides(cleared), 2);
  // Clearing something that was never set changes nothing.
  assert.equal(clearOverride(cleared, 999), cleared);
});

test("setOverrideEntries merges a mixed batch in one pass", () => {
  const start = setOverride({}, 10, CLASS_DAMAGED);
  const merged = setOverrideEntries(start, [
    { id: 10, class: CLASS_NOT_DAMAGED },
    { id: 11, class: CLASS_UNKNOWN },
    { id: 12, class: "Nonsense" },
    { id: null, class: CLASS_DAMAGED },
  ]);
  assert.equal(getOverride(merged, 10), CLASS_NOT_DAMAGED);
  assert.equal(getOverride(merged, 11), CLASS_UNKNOWN);
  assert.equal(getOverride(merged, 12), null);
  assert.equal(countOverrides(merged), 2);
  assert.deepEqual(start, { 10: CLASS_DAMAGED }, "input map must not change");
  // Nothing to apply -> same object back.
  assert.equal(setOverrideEntries(merged, []), merged);
});

test("resolveClassAt prefers the user override over the derived class", () => {
  const attrs = sampleAttrs();
  const overrides = setOverride({}, 13, CLASS_NOT_DAMAGED);
  assert.equal(
    resolveClassAt(attrs, 3, { threshold: 0.5 }),
    CLASS_DAMAGED,
    "derived without an override"
  );
  assert.equal(
    resolveClassAt(attrs, 3, { threshold: 0.5, overrides }),
    CLASS_NOT_DAMAGED
  );
});

test("classifyAll counts every class and tracks edits", () => {
  const attrs = sampleAttrs();
  const result = classifyAll(attrs, { threshold: 0.5, unknownThreshold: 0 });

  assert.deepEqual(result.classes, [
    CLASS_NOT_DAMAGED, // 0.05
    CLASS_NOT_DAMAGED, // 0.5 is not > 0.5
    CLASS_DAMAGED, // 0.51
    CLASS_DAMAGED, // 0.9
    CLASS_UNKNOWN, // unknown 0.4 > 0
  ]);
  assert.deepEqual(result.counts, {
    [CLASS_DAMAGED]: 2,
    [CLASS_NOT_DAMAGED]: 2,
    [CLASS_UNKNOWN]: 1,
  });
  assert.equal(result.editedCount, 0);
  assert.equal(result.total, 5);

  const edited = classifyAll(attrs, {
    threshold: 0.5,
    overrides: setOverride({}, 10, CLASS_DAMAGED),
  });
  assert.equal(edited.classes[0], CLASS_DAMAGED);
  assert.equal(edited.edited[0], true);
  assert.equal(edited.edited[1], false);
  assert.equal(edited.editedCount, 1);
  assert.equal(edited.counts[CLASS_DAMAGED], 3);
});

test("lowering the threshold reclassifies without touching the data", () => {
  const attrs = sampleAttrs();
  const strict = classifyAll(attrs, { threshold: 0.95 });
  assert.equal(strict.counts[CLASS_DAMAGED], 0);

  const loose = classifyAll(attrs, { threshold: 0.01 });
  // Building 4 still has a non-zero unknown score, so it stays Unknown.
  assert.equal(loose.counts[CLASS_DAMAGED], 4);
  assert.equal(loose.counts[CLASS_UNKNOWN], 1);
});

test("filter predicate covers class filters, edited, and all", () => {
  assert.equal(matchesFilter(CLASS_DAMAGED, false, FILTER_ALL), true);
  assert.equal(matchesFilter(CLASS_DAMAGED, false, CLASS_DAMAGED), true);
  assert.equal(matchesFilter(CLASS_DAMAGED, false, CLASS_UNKNOWN), false);
  assert.equal(matchesFilter(CLASS_DAMAGED, false, FILTER_EDITED), false);
  assert.equal(matchesFilter(CLASS_DAMAGED, true, FILTER_EDITED), true);
  assert.equal(matchesFilter(CLASS_UNKNOWN, false, undefined), true);
});

test("filterIndices returns the rows the panel traverses", () => {
  const attrs = sampleAttrs();
  const classification = classifyAll(attrs, {
    threshold: 0.5,
    overrides: setOverride({}, 11, CLASS_UNKNOWN),
  });

  assert.deepEqual(filterIndices(classification, FILTER_ALL), [0, 1, 2, 3, 4]);
  assert.deepEqual(filterIndices(classification, CLASS_DAMAGED), [2, 3]);
  assert.deepEqual(filterIndices(classification, CLASS_UNKNOWN), [1, 4]);
  assert.deepEqual(filterIndices(classification, FILTER_EDITED), [1]);
});

test("countClassChanges reports how many buildings a slider move flips", () => {
  const attrs = sampleAttrs();
  const base = { threshold: 0.5, unknownThreshold: 0 };

  assert.equal(countClassChanges(attrs, base, base), 0);

  // 0.5 -> 0.85 demotes 0.51 and 0.8 (0.8 is Unknown, so it doesn't count)
  // leaving only building index 2.
  assert.equal(
    countClassChanges(attrs, base, { threshold: 0.85, unknownThreshold: 0 }),
    1
  );

  // 0.5 -> 0.01 promotes 0.05 and 0.5.
  assert.equal(
    countClassChanges(attrs, base, { threshold: 0.01, unknownThreshold: 0 }),
    2
  );

  // Raising the unknown threshold releases building 4 back to Damaged.
  assert.equal(
    countClassChanges(attrs, base, { threshold: 0.5, unknownThreshold: 0.5 }),
    1
  );
});

test("countClassChanges ignores buildings the user pinned", () => {
  const attrs = sampleAttrs();
  const base = { threshold: 0.5, unknownThreshold: 0 };
  const candidate = { threshold: 0.01, unknownThreshold: 0 };

  assert.equal(countClassChanges(attrs, base, candidate), 2);
  // Pin one of the two that would have flipped.
  const overrides = setOverride({}, 10, CLASS_NOT_DAMAGED);
  assert.equal(countClassChanges(attrs, base, candidate, overrides), 1);
});

test("cycleClass walks Damaged -> NotDamaged -> Unknown -> Damaged", () => {
  assert.equal(cycleClass(CLASS_DAMAGED), CLASS_NOT_DAMAGED);
  assert.equal(cycleClass(CLASS_NOT_DAMAGED), CLASS_UNKNOWN);
  assert.equal(cycleClass(CLASS_UNKNOWN), CLASS_DAMAGED);
  assert.equal(cycleClass(undefined), CLASS_DAMAGED);
});

test("nextIndexInList wraps in both directions", () => {
  const list = [2, 5, 9];
  assert.equal(nextIndexInList(list, 2, 1), 5);
  assert.equal(nextIndexInList(list, 9, 1), 2);
  assert.equal(nextIndexInList(list, 2, -1), 9);
  assert.equal(nextIndexInList(list, 5, -1), 2);
  assert.equal(nextIndexInList([], 0, 1), null);
});

test("nextIndexInList handles a selection outside the filtered set", () => {
  const list = [2, 5, 9];
  // Nothing selected yet.
  assert.equal(nextIndexInList(list, -1, 1), 2);
  assert.equal(nextIndexInList(list, -1, -1), 9);
  // Selection filtered out: step to the nearest neighbour in the direction
  // of travel.
  assert.equal(nextIndexInList(list, 6, 1), 9);
  assert.equal(nextIndexInList(list, 6, -1), 5);
  assert.equal(nextIndexInList(list, 12, 1), 2);
});

test("nextIndexInList prefers candidates but never refuses to move", () => {
  const list = [2, 5, 9];
  const located = new Set([9]);
  // Skips 5 because its geometry hasn't streamed in yet.
  assert.equal(nextIndexInList(list, 2, 1, (i) => located.has(i)), 9);
  // Nothing qualifies -> plain next entry.
  assert.equal(nextIndexInList(list, 2, 1, () => false), 5);
});

test("toOverrideList produces the sparse, sorted payload list", () => {
  const overrides = setOverrides({}, [14, 10, 12], CLASS_DAMAGED);
  assert.deepEqual(toOverrideList(overrides), [
    { id: 10, class: CLASS_DAMAGED },
    { id: 12, class: CLASS_DAMAGED },
    { id: 14, class: CLASS_DAMAGED },
  ]);
  assert.deepEqual(toOverrideList({}), []);
  assert.deepEqual(toOverrideList(null), []);
});

test("buildSavePayload matches the PutEditedPredictions contract", () => {
  const payload = buildSavePayload({
    projectId: "p1",
    imageLayerId: "l1",
    modelId: "m1",
    threshold: 0.42,
    unknownThreshold: 0.1,
    overrides: setOverride({}, 7, CLASS_UNKNOWN),
  });
  assert.deepEqual(payload, {
    projectId: "p1",
    imageLayerId: "l1",
    modelId: "m1",
    threshold: 0.42,
    unknownThreshold: 0.1,
    overrides: [{ id: 7, class: CLASS_UNKNOWN }],
  });
});

test("version helpers order the history newest-first", () => {
  const versions = [
    { version: 1, threshold: 0.5 },
    { version: 3, threshold: 0.7 },
    { version: 2, threshold: 0.6 },
  ];
  assert.equal(latestVersion(versions).version, 3);
  assert.deepEqual(
    sortVersionsDescending(versions).map((v) => v.version),
    [3, 2, 1]
  );
  assert.equal(latestVersion([]), null);
  assert.equal(latestVersion(undefined), null);
});

test("toPercentLabel renders fractions as percentages", () => {
  assert.equal(toPercentLabel(0.5), "50%");
  assert.equal(toPercentLabel(0.517, 1), "51.7%");
  assert.equal(toPercentLabel(undefined), "—");
});

// ── Preparation / polling state (predictionPrep.js) ─────────────────────────
// The editor cannot draw anything until the queued prep job has written the
// footprint PMTiles and the score sidecar, so the "trigger it, then wait"
// decisions are pure functions and get tested here rather than inside the
// component.

test("normalizePrepStatus accepts the repo status vocabulary defensively", () => {
  assert.equal(normalizePrepStatus("Queued"), PREP_STATUS_QUEUED);
  assert.equal(normalizePrepStatus("InProgress"), PREP_STATUS_IN_PROGRESS);
  // Case and stray whitespace must not break the state machine.
  assert.equal(normalizePrepStatus(" inprogress "), PREP_STATUS_IN_PROGRESS);
  // Anything unknown collapses to "" — treated as "not terminal, keep going".
  assert.equal(normalizePrepStatus("Exploded"), "");
  assert.equal(normalizePrepStatus(undefined), "");
  assert.equal(normalizePrepStatus(null), "");
  assert.equal(normalizePrepStatus(42), "");
});

test("only Failed and Cancelled are terminal", () => {
  assert.equal(isTerminalPrepStatus(PREP_STATUS_FAILED), true);
  assert.equal(isTerminalPrepStatus(PREP_STATUS_CANCELLED), true);
  assert.equal(isTerminalPrepStatus(PREP_STATUS_QUEUED), false);
  assert.equal(isTerminalPrepStatus(PREP_STATUS_IN_PROGRESS), false);
  assert.equal(isTerminalPrepStatus("Processed"), false);
  assert.equal(isTerminalPrepStatus(undefined), false);
});

test("isPrepReady requires both artifacts and never assumes readiness", () => {
  assert.equal(isPrepReady({ tilesReady: true, attrsReady: true }), true);
  assert.equal(isPrepReady({ tilesReady: true, attrsReady: false }), false);
  assert.equal(isPrepReady({ tilesReady: false, attrsReady: true }), false);
  // A backend that omits the flags entirely means "not ready".
  assert.equal(isPrepReady({}), false);
  assert.equal(isPrepReady(null), false);
  // Truthy-but-not-true values are not readiness either.
  assert.equal(isPrepReady({ tilesReady: 1, attrsReady: "yes" }), false);
});

test("evaluatePrepState keeps polling while the job is queued or running", () => {
  const queued = evaluatePrepState(
    { tilesReady: false, attrsReady: false, predictionTilesStatus: "Queued" },
    0
  );
  assert.equal(queued.phase, PREP_PHASE_WAITING);
  assert.equal(queued.shouldPoll, true);
  assert.equal(queued.ready, false);
  assert.equal(queued.status, PREP_STATUS_QUEUED);
  assert.equal(shouldPollPrep(queued.phase), true);

  // Unknown/missing status is not an error: keep waiting.
  const unknown = evaluatePrepState({ tilesReady: false, attrsReady: false }, 3);
  assert.equal(unknown.phase, PREP_PHASE_WAITING);
  assert.equal(unknown.status, "");
  assert.equal(unknown.attempt, 3);

  // Half-prepared is still not ready.
  const half = evaluatePrepState(
    { tilesReady: true, attrsReady: false, predictionTilesStatus: "InProgress" },
    1
  );
  assert.equal(half.phase, PREP_PHASE_WAITING);
});

test("evaluatePrepState stops as soon as both artifacts exist", () => {
  const ready = evaluatePrepState(
    { tilesReady: true, attrsReady: true, predictionTilesStatus: "Processed" },
    7
  );
  assert.equal(ready.phase, PREP_PHASE_READY);
  assert.equal(ready.ready, true);
  assert.equal(ready.shouldPoll, false);
  assert.equal(shouldPollPrep(ready.phase), false);
});

test("existing artifacts win over a stale Failed status", () => {
  // A previous run failed, but the files are on disk: the editor can open, so
  // it must open rather than showing an error.
  const result = evaluatePrepState(
    { tilesReady: true, attrsReady: true, predictionTilesStatus: "Failed" },
    2
  );
  assert.equal(result.phase, PREP_PHASE_READY);
  assert.equal(result.shouldPoll, false);
});

test("evaluatePrepState treats Failed and Cancelled as terminal", () => {
  for (const status of [PREP_STATUS_FAILED, PREP_STATUS_CANCELLED]) {
    const result = evaluatePrepState(
      {
        tilesReady: false,
        attrsReady: false,
        predictionTilesStatus: status,
        predictionTilesStatusMessage: "tippecanoe exited 1",
      },
      4
    );
    assert.equal(result.phase, PREP_PHASE_FAILED);
    assert.equal(result.shouldPoll, false);
    assert.equal(result.status, status);
    assert.equal(result.statusMessage, "tippecanoe exited 1");
  }
});

test("evaluatePrepState gives up at the attempt cap", () => {
  const running = { tilesReady: false, attrsReady: false, predictionTilesStatus: "InProgress" };
  const justUnder = evaluatePrepState(running, MAX_PREP_POLL_ATTEMPTS - 1);
  assert.equal(justUnder.phase, PREP_PHASE_WAITING);

  const atCap = evaluatePrepState(running, MAX_PREP_POLL_ATTEMPTS);
  assert.equal(atCap.phase, PREP_PHASE_TIMED_OUT);
  assert.equal(atCap.shouldPoll, false);

  // A tighter cap (used by the test below) short-circuits the same way.
  assert.equal(evaluatePrepState(running, 3, 3).phase, PREP_PHASE_TIMED_OUT);
});

test("evaluatePrepState reads the status off an enqueue response too", () => {
  // PutPreparePredictionTilesQueueMessage returns `status`, the session
  // returns `predictionTilesStatus`; both must be understood.
  const result = evaluatePrepState(
    { tilesReady: false, attrsReady: false, status: "Failed" },
    0
  );
  assert.equal(result.phase, PREP_PHASE_FAILED);
});

test("nextPollAttempt counts up and repairs junk input", () => {
  assert.equal(nextPollAttempt(0), 1);
  assert.equal(nextPollAttempt(1), 2);
  assert.equal(nextPollAttempt(undefined), 1);
  assert.equal(nextPollAttempt(-5), 1);
  assert.equal(nextPollAttempt(NaN), 1);
  assert.equal(nextPollAttempt(2.7), 3);
});

test("a transient poll error keeps waiting until the cap", () => {
  const current = {
    phase: PREP_PHASE_WAITING,
    status: PREP_STATUS_IN_PROGRESS,
    statusMessage: "reprojecting",
    attempt: 1,
  };
  const blip = prepStateAfterPollError(current, "Error fetching.", 5);
  assert.equal(blip.phase, PREP_PHASE_WAITING);
  assert.equal(blip.shouldPoll, true);
  assert.equal(blip.attempt, 2);
  // The last known good status survives the blip so the card doesn't reset.
  assert.equal(blip.status, PREP_STATUS_IN_PROGRESS);
  assert.equal(blip.statusMessage, "reprojecting");
  assert.equal(blip.error, "Error fetching.");

  // Repeated failures still terminate at the cap.
  const exhausted = prepStateAfterPollError({ ...current, attempt: 4 }, "", 5);
  assert.equal(exhausted.phase, PREP_PHASE_TIMED_OUT);
  assert.equal(exhausted.shouldPoll, false);
  assert.equal(exhausted.error, "The preparation status could not be read.");
});

test("a polling run always terminates within the cap", () => {
  // Drive the state machine the way the component does — evaluate, count,
  // repeat — against a job that never finishes, and prove it stops.
  const stuck = { tilesReady: false, attrsReady: false, predictionTilesStatus: "InProgress" };
  const cap = 8;
  let state = evaluatePrepState(stuck, 0, cap);
  let polls = 0;
  while (shouldPollPrep(state.phase)) {
    polls++;
    assert.ok(polls <= cap, "must not poll past the cap");
    state = evaluatePrepState(stuck, nextPollAttempt(state.attempt), cap);
  }
  assert.equal(state.phase, PREP_PHASE_TIMED_OUT);
  assert.equal(polls, cap);

  // The same loop against a job that finishes on the third poll stops early.
  let finished = evaluatePrepState(stuck, 0, cap);
  let ticks = 0;
  while (shouldPollPrep(finished.phase)) {
    ticks++;
    const session = ticks < 3 ? stuck : { tilesReady: true, attrsReady: true };
    finished = evaluatePrepState(session, nextPollAttempt(finished.attempt), cap);
  }
  assert.equal(finished.phase, PREP_PHASE_READY);
  assert.equal(ticks, 3);
});

test("the poll interval and cap are a sane bounded wait", () => {
  assert.equal(PREP_POLL_INTERVAL_MS, 5000);
  // 360 x 5s = 30 minutes: generous for a container-runner job, finite for a
  // forgotten tab.
  assert.equal((MAX_PREP_POLL_ATTEMPTS * PREP_POLL_INTERVAL_MS) / 60000, 30);
});

test("buildPrepRequest only sends force when retrying", () => {
  assert.deepEqual(
    buildPrepRequest({ projectId: "p1", imageLayerId: "l1", modelId: "m1" }),
    { projectId: "p1", imageLayerId: "l1", modelId: "m1" }
  );
  assert.deepEqual(
    buildPrepRequest({
      projectId: "p1",
      imageLayerId: "l1",
      modelId: "m1",
      force: true,
    }),
    { projectId: "p1", imageLayerId: "l1", modelId: "m1", force: true }
  );
});

test("applyPrepResponse folds the enqueue reply into the session", () => {
  const session = {
    buildingCount: 10,
    tilesReady: false,
    attrsReady: false,
    predictionTilesStatus: "Failed",
  };
  const merged = applyPrepResponse(session, {
    queued: true,
    tilesReady: false,
    attrsReady: true,
    status: "Queued",
  });
  assert.equal(merged.predictionTilesStatus, PREP_STATUS_QUEUED);
  assert.equal(merged.attrsReady, true);
  assert.equal(merged.tilesReady, false);
  assert.equal(merged.buildingCount, 10, "unrelated fields survive");
  assert.deepEqual(session.predictionTilesStatus, "Failed", "input unchanged");

  // apiPut hands back a bare 409 for a conflict, and a dead endpoint can give
  // us anything at all — keep the session we already have.
  assert.equal(applyPrepResponse(session, 409), session);
  assert.equal(applyPrepResponse(session, null), session);
  assert.equal(applyPrepResponse(session, "nope"), session);
  assert.equal(applyPrepResponse(session, []), session);
  assert.deepEqual(applyPrepResponse(null, null), {});
});

test("prep card copy reports what is outstanding", () => {
  assert.equal(
    describeOutstandingArtifacts({ tilesReady: false, attrsReady: false }),
    "Still generating footprint tiles and per-building prediction scores."
  );
  assert.equal(
    describeOutstandingArtifacts({ tilesReady: true, attrsReady: false }),
    "Still generating per-building prediction scores."
  );
  assert.equal(
    describeOutstandingArtifacts({ tilesReady: true, attrsReady: true }),
    ""
  );

  assert.equal(prepStatusLabel(PREP_STATUS_QUEUED), "Queued");
  assert.equal(prepStatusLabel(PREP_STATUS_IN_PROGRESS), "In progress");
  assert.equal(prepStatusLabel(PREP_STATUS_FAILED), "Failed");
  assert.equal(prepStatusLabel(PREP_STATUS_CANCELLED), "Cancelled");
  // Unknown/missing must still render something sensible.
  assert.equal(prepStatusLabel(undefined), "Starting");
  assert.equal(prepStatusLabel("Weird"), "Starting");
});

// ── Swipe comparison map (predictionSwipe.js) ───────────────────────────────

test("swipe mode follows the imagery the layer actually has", () => {
  // Pre-event tiles present: compare pre against post.
  assert.equal(
    resolveSwipeMode({
      preEventTileUrl: "https://x/pre/{z}/{x}/{y}.png",
      postEventTileUrl: "https://x/post/{z}/{x}/{y}.png",
    }),
    SWIPE_MODE_PRE_POST
  );

  // No pre-event tiles: the basemap stands in on the comparison pane.
  assert.equal(
    resolveSwipeMode({ postEventTileUrl: "https://x/post/{z}/{x}/{y}.png" }),
    SWIPE_MODE_BASEMAP_POST
  );
  assert.equal(
    resolveSwipeMode({
      preEventTileUrl: "   ",
      postEventTileUrl: "https://x/post/{z}/{x}/{y}.png",
    }),
    SWIPE_MODE_BASEMAP_POST,
    "a blank pre URL is not pre-event imagery"
  );

  // Without post-event imagery there is nothing to compare against, so the
  // editor must not offer a swipe at all.
  assert.equal(resolveSwipeMode(null), SWIPE_MODE_NONE);
  assert.equal(resolveSwipeMode(undefined), SWIPE_MODE_NONE);
  assert.equal(resolveSwipeMode({}), SWIPE_MODE_NONE);
  assert.equal(
    resolveSwipeMode({ preEventTileUrl: "https://x/pre/{z}/{x}/{y}.png" }),
    SWIPE_MODE_NONE
  );

  assert.equal(isSwipeAvailable(SWIPE_MODE_PRE_POST), true);
  assert.equal(isSwipeAvailable(SWIPE_MODE_BASEMAP_POST), true);
  assert.equal(isSwipeAvailable(SWIPE_MODE_NONE), false);
  assert.equal(isSwipeAvailable(undefined), false);
});

test("only the pre/post mode overlays imagery on the comparison pane", () => {
  const imagery = {
    preEventTileUrl: " https://x/pre/{z}/{x}/{y}.png ",
    postEventTileUrl: "https://x/post/{z}/{x}/{y}.png",
  };
  assert.equal(
    swipeComparisonTileUrl(imagery, SWIPE_MODE_PRE_POST),
    "https://x/pre/{z}/{x}/{y}.png"
  );
  // Basemap mode draws the map's own basemap — no tile layer on top.
  assert.equal(swipeComparisonTileUrl(imagery, SWIPE_MODE_BASEMAP_POST), "");
  assert.equal(swipeComparisonTileUrl(imagery, SWIPE_MODE_NONE), "");
  assert.equal(swipeComparisonTileUrl(null, SWIPE_MODE_PRE_POST), "");
});

test("swipe labels name the comparison the analyst is getting", () => {
  assert.equal(
    swipeToggleLabel(SWIPE_MODE_PRE_POST),
    "Swipe: pre-event vs post-event"
  );
  assert.equal(
    swipeToggleLabel(SWIPE_MODE_BASEMAP_POST),
    "Swipe: basemap vs post-event"
  );
  assert.equal(
    swipeToggleLabel(SWIPE_MODE_NONE),
    "Swipe comparison unavailable"
  );

  assert.equal(swipeLeftPaneLabel(SWIPE_MODE_PRE_POST), "Pre-event imagery");
  assert.equal(swipeLeftPaneLabel(SWIPE_MODE_BASEMAP_POST), "Basemap");
  assert.equal(swipeLeftPaneLabel(SWIPE_MODE_NONE), "");
  assert.equal(
    swipeRightPaneLabel(SWIPE_MODE_PRE_POST),
    "Post-event imagery"
  );
  assert.equal(
    swipeRightPaneLabel(SWIPE_MODE_BASEMAP_POST),
    "Post-event imagery"
  );
  assert.equal(swipeRightPaneLabel(SWIPE_MODE_NONE), "");
});

test("swipe hint describes the divider directions the right way round", () => {
  // The comparison map is the SwipeMap PRIMARY and sits LEFT of the divider,
  // so dragging LEFT uncovers MORE post-event imagery. A previous PR shipped
  // this backwards; pin it down.
  const hint = swipeModeHint(SWIPE_MODE_PRE_POST);
  assert.match(hint, /Pre-event imagery sits left of the divider/);
  assert.match(hint, /left for more post-event/);
  assert.match(hint, /right for more pre-event imagery/);
  assert.match(hint, /Editing works on both sides/);
  assert.match(
    swipeModeHint(SWIPE_MODE_BASEMAP_POST),
    /Basemap sits left of the divider/
  );
  assert.match(
    swipeModeHint(SWIPE_MODE_NONE),
    /no post-event imagery to compare against/
  );
});

test("A / S / D snap the divider left / centre / right", () => {
  assert.equal(dividerPositionForKey("a", 800), 0);
  assert.equal(dividerPositionForKey("s", 800), 400);
  assert.equal(dividerPositionForKey("d", 800), 800);
  // Shift-held (or caps-locked) keys are the same shortcut.
  assert.equal(dividerPositionForKey("A", 800), 0);
  assert.equal(dividerPositionForKey("S", 800), 400);
  assert.equal(dividerPositionForKey("D", 800), 800);

  // Anything else is not ours to handle.
  for (const key of ["1", "w", "ArrowLeft", " ", "", null, undefined, 5]) {
    assert.equal(dividerPositionForKey(key, 800), null);
  }

  // No usable width yet (map area not laid out): do nothing rather than
  // silently park the divider at 0.
  for (const width of [0, -10, NaN, Infinity, null, undefined, "wide"]) {
    assert.equal(dividerPositionForKey("s", width), null);
  }
  assert.equal(dividerPositionForKey("s", "800"), 400, "numeric strings work");
});
