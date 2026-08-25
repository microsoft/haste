// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Run with: node --test src/Components/Visualizer/predictionClassify.test.js
//
// Covers every pure module behind the results page's predicted-building
// layer: class derivation and overrides (predictionClassify.js), the
// preparation-job state machine (predictionPrep.js), the swipe divider
// (visualizerSwipe.js), the layer/status decisions the page renders from
// (predictionResults.js), the version selector's options, URLs and
// disclosures (predictionVersions.js) and the renderer helpers that paint the
// footprints (predictionFootprintMap.js). None of them may import React,
// Azure Maps or FluentUI — this file is run by plain `node --test`.

import test from "node:test";
import assert from "node:assert/strict";

import {
  CLASS_DAMAGED,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
  DEFAULT_EDIT_CLASS,
  FILTER_ALL,
  FILTER_EDITED,
  PREDICTION_CLASSES,
  baseClassAt,
  buildSavePayload,
  classifyAll,
  clearOverride,
  countClassChanges,
  countOverrides,
  deriveClass,
  filterIndices,
  getOverride,
  hasSavedClasses,
  indexById,
  latestVersion,
  matchesFilter,
  mergedOverrideList,
  nextIndexInList,
  normalizeAttrs,
  normalizeEditClass,
  resolveClassAt,
  savedClassAt,
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
  describePendingVersions,
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
  swipeLeftPaneLabel,
  swipeModeHint,
  swipeRightPaneLabel,
} from "./visualizerSwipe.js";
import {
  FLAVOR_EMBEDDING,
  FLAVOR_INFERENCE,
  FOOTPRINTS_EMPTY,
  FOOTPRINTS_LOADING,
  FOOTPRINTS_PREPARING,
  FOOTPRINTS_READY,
  FOOTPRINTS_UNAVAILABLE,
  buildArtifactUrl,
  canEditFootprints,
  countUnsavedOverrides,
  describeEditAvailability,
  describeFootprintStatus,
  describeServedVersion,
  describeUnsavedEdits,
  hasAnyRasterLayer,
  hasRasterLayer,
  hasUnsavedEdits,
  normalizeVersionParam,
  rasterLayerAvailability,
  resolveActiveVersion,
  resolveFootprintStatus,
  resolveModelFlavor,
  resolvePredictionArtifacts,
  resolveInitialBuildingCount,
  resolveInitialVersions,
  resolvePredictionsReady,
  resolveReadinessDetail,
  resolveReadinessReason,
  resolveVersionIsLatest,
  shouldRequestPreparation,
  statusForReadinessReason,
  resolveSupportsThreshold,
  sameOverrides,
  versionSidecarPending,
  visualizerLayerOptions,
} from "./predictionResults.js";
import {
  MAX_VERSION_POLL_ATTEMPTS,
  RAW_VERSION,
  RAW_VERSION_LABEL,
  VERSION_POLL_INTERVAL_MS,
  VERSION_PREPARING_REASON,
  buildVersionGpkgUrl,
  buildVisualizerResultsUrl,
  describeReportDivergence,
  describeSavedClassNote,
  describeVersionDownload,
  describeVersionInline,
  describeVersionSidecarPending,
  describeVersionSwitchDiscard,
  describeVersionSwitchFailure,
  findVersionOption,
  isVersionReady,
  normalizeVersionSelection,
  selectedVersionText,
  shouldPollVersionSidecar,
  versionKey,
  versionLabel,
  versionSelectorOptions,
} from "./predictionVersions.js";
import {
  CLASS_CODES,
  FALLBACK_COLORS,
  FILL_OPACITY_EXPRESSION,
  PMTILES_SOURCE_LAYER,
  classCode,
  discoverFillLayerIds,
  discoverVectorSourceId,
  featureCentroid,
  fillColorExpression,
  findGlMap,
  footprintFeatureState,
  normalizeSelectionBox,
  resolveMapColors,
  strokeColorExpression,
  themeColorLookup,
} from "./predictionFootprintMap.js";

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

test("normalizeEditClass accepts only the three real classes", () => {
  assert.equal(normalizeEditClass(CLASS_DAMAGED), CLASS_DAMAGED);
  assert.equal(normalizeEditClass(CLASS_NOT_DAMAGED), CLASS_NOT_DAMAGED);
  assert.equal(normalizeEditClass(CLASS_UNKNOWN), CLASS_UNKNOWN);
  // "cycle" was the old click-action sentinel; it must never reach an
  // override now that the picker is the only source of a class.
  assert.equal(normalizeEditClass("cycle"), "");
  assert.equal(normalizeEditClass(""), "");
  assert.equal(normalizeEditClass(undefined), "");
  assert.equal(normalizeEditClass(null), "");
});

test("the editor starts on a class that is safe to paint with", () => {
  assert.equal(normalizeEditClass(DEFAULT_EDIT_CLASS), DEFAULT_EDIT_CLASS);
  assert.ok(PREDICTION_CLASSES.includes(DEFAULT_EDIT_CLASS));
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

// ── Swipe comparison map (visualizerSwipe.js) ───────────────────────────────

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

test("swipe mode also reads the results payload's imagery blocks", () => {
  // The results page is handed GetVisualizerResults, not the labeling tool's
  // flat tile URLs, so both shapes have to resolve the same way.
  assert.equal(
    resolveSwipeMode({
      preDisasterImagery: { url: "https://x/pre/{z}/{x}/{y}.png" },
      postDisasterImagery: { url: "https://x/post/{z}/{x}/{y}.png" },
    }),
    SWIPE_MODE_PRE_POST
  );
  assert.equal(
    resolveSwipeMode({
      preDisasterImagery: { url: "" },
      postDisasterImagery: { url: "https://x/post/{z}/{x}/{y}.png" },
    }),
    SWIPE_MODE_BASEMAP_POST
  );
  // An embedding model has no processed imagery at all: no comparison.
  assert.equal(
    resolveSwipeMode({ preDisasterImagery: null, postDisasterImagery: null }),
    SWIPE_MODE_NONE
  );
});

test("swipe labels name the comparison the analyst is getting", () => {
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

// ── Results-page layer decisions (predictionResults.js) ─────────────────────

test("a raster only counts as present when it can actually be fetched", () => {
  assert.equal(
    hasRasterLayer({ url: "https://titiler/cog/tiles/{z}/{x}/{y}?url=abfs://x" }),
    true
  );

  // An embedding model has no COG, but GetVisualizerResults still builds its
  // TiTiler template by interpolation, so the layer arrives with an EMPTY
  // `url=` parameter. Requesting those tiles can only 404.
  assert.equal(
    hasRasterLayer({ url: "https://titiler/cog/tiles/{z}/{x}/{y}?scale=1&url=" }),
    false
  );
  assert.equal(
    hasRasterLayer({ url: "https://titiler/cog/tiles/{z}/{x}/{y}?url=&scale=1" }),
    false
  );

  assert.equal(hasRasterLayer(null), false);
  assert.equal(hasRasterLayer(undefined), false);
  assert.equal(hasRasterLayer({}), false);
  assert.equal(hasRasterLayer({ url: "" }), false);
  assert.equal(hasRasterLayer({ url: "   " }), false);
  assert.equal(hasRasterLayer({ url: 42 }), false);
});

test("raster availability drives what the results page can offer", () => {
  const inference = {
    predictedDamageLayer: { url: "https://titiler/a?url=abfs://v.tif" },
    predictionsLayer: { url: "https://titiler/b?url=abfs://p.tif" },
  };
  assert.deepEqual(rasterLayerAvailability(inference), {
    predictedDamageLayer: true,
    predictionsLayer: true,
  });
  assert.equal(hasAnyRasterLayer(inference), true);

  // The embedding workflow: no rasters at all, which is exactly why the page
  // needs the vector footprints.
  const embedding = { predictedDamageLayer: null, predictionsLayer: null };
  assert.deepEqual(rasterLayerAvailability(embedding), {
    predictedDamageLayer: false,
    predictionsLayer: false,
  });
  assert.equal(hasAnyRasterLayer(embedding), false);
  assert.equal(hasAnyRasterLayer(null), false);
});

test("artifact URLs prefer the server's own and fall back to the standard route", () => {
  const ids = { projectId: "p1", imageLayerId: "l1", modelId: "m1" };
  assert.equal(
    buildArtifactUrl({ ...ids, kind: "footprint_pmtiles" }),
    "GetModelArtifact?projectId=p1&imageLayerId=l1&modelId=m1&kind=footprint_pmtiles"
  );
  // imageLayerId is optional in the contract; leave it out rather than send
  // an empty one.
  assert.equal(
    buildArtifactUrl({ projectId: "p1", modelId: "m1", kind: "prediction_attrs" }),
    "GetModelArtifact?projectId=p1&modelId=m1&kind=prediction_attrs"
  );
  // Ids are escaped, never concatenated raw.
  assert.match(
    buildArtifactUrl({ projectId: "a b&c", modelId: "m", kind: "k" }),
    /projectId=a\+b%26c/
  );

  // The vector-first payload wins when it is there...
  assert.deepEqual(
    resolvePredictionArtifacts(
      {
        footprintTilesUrl: "GetModelArtifact?x=1&kind=footprint_pmtiles",
        predictionAttrsUrl: "GetModelArtifact?x=1&kind=prediction_attrs",
      },
      ids
    ),
    {
      footprintTilesUrl: "GetModelArtifact?x=1&kind=footprint_pmtiles",
      predictionAttrsUrl: "GetModelArtifact?x=1&kind=prediction_attrs",
      // Nothing was pinned, so this payload is the model's raw output.
      version: null,
    }
  );
  // ...and today's payload, which has neither field, still resolves.
  assert.deepEqual(resolvePredictionArtifacts({}, ids), {
    footprintTilesUrl:
      "GetModelArtifact?projectId=p1&imageLayerId=l1&modelId=m1&kind=footprint_pmtiles",
    predictionAttrsUrl:
      "GetModelArtifact?projectId=p1&imageLayerId=l1&modelId=m1&kind=prediction_attrs",
    version: null,
  });
});

test("flavor and threshold support come from the session first", () => {
  assert.equal(
    resolveModelFlavor({ session: { flavor: FLAVOR_EMBEDDING }, results: { flavor: FLAVOR_INFERENCE } }),
    FLAVOR_EMBEDDING
  );
  assert.equal(
    resolveModelFlavor({ results: { flavor: FLAVOR_INFERENCE } }),
    FLAVOR_INFERENCE
  );
  assert.equal(resolveModelFlavor({}), "");
  assert.equal(resolveModelFlavor(), "");

  // An embedding model's damage_pct_0m is a degenerate 0/1 copy of the class,
  // so re-thresholding it is meaningless and the slider must not appear.
  assert.equal(
    resolveSupportsThreshold({ session: { flavor: FLAVOR_EMBEDDING } }),
    false
  );
  assert.equal(
    resolveSupportsThreshold({ results: { flavor: FLAVOR_EMBEDDING } }),
    false
  );
  // An explicit flag always wins over the flavour guess.
  assert.equal(
    resolveSupportsThreshold({
      session: { flavor: FLAVOR_EMBEDDING, supportsThreshold: true },
    }),
    true
  );
  assert.equal(
    resolveSupportsThreshold({ results: { supportsThreshold: false } }),
    false
  );
  // Nothing said anything: assume the slider works, because hiding it would
  // silently remove the feature from every inference model.
  assert.equal(resolveSupportsThreshold({}), true);
  assert.equal(resolveSupportsThreshold(), true);
});

test("readiness prefers the session's per-artifact flags", () => {
  assert.equal(
    resolvePredictionsReady({
      session: { tilesReady: true, attrsReady: true },
      results: { predictionsReady: false },
    }),
    true
  );
  assert.equal(
    resolvePredictionsReady({ session: { tilesReady: true, attrsReady: false } }),
    false
  );
  assert.equal(resolvePredictionsReady({ results: { predictionsReady: true } }), true);
  assert.equal(resolvePredictionsReady({ results: { predictionsReady: false } }), false);
  // Today's payload says nothing: "unknown", not "not ready".
  assert.equal(resolvePredictionsReady({ results: {} }), null);
  assert.equal(resolvePredictionsReady(), null);
});

test("what the results payload already knows is not thrown away", () => {
  // Zero is a real answer — it is the difference between "still preparing"
  // and "there is nothing to prepare" — so it must survive.
  assert.equal(resolveInitialBuildingCount({ buildingCount: 0 }), 0);
  assert.equal(resolveInitialBuildingCount({ buildingCount: 1234 }), 1234);
  assert.equal(resolveInitialBuildingCount({ buildingCount: "42" }), 42);
  assert.equal(resolveInitialBuildingCount({}), null);
  assert.equal(resolveInitialBuildingCount({ buildingCount: null }), null);
  assert.equal(resolveInitialBuildingCount({ buildingCount: "" }), null);
  assert.equal(resolveInitialBuildingCount({ buildingCount: "many" }), null);
  assert.equal(resolveInitialBuildingCount({ buildingCount: -3 }), null);
  assert.equal(resolveInitialBuildingCount(), null);

  // The saved versions ride along with the results, so the history is
  // populated before any edit session is fetched.
  const versions = [{ version: 2 }, { version: 1 }];
  assert.deepEqual(
    resolveInitialVersions({ predictionVersions: versions }),
    versions
  );
  assert.deepEqual(resolveInitialVersions({}), []);
  assert.deepEqual(resolveInitialVersions({ predictionVersions: "2" }), []);
  assert.deepEqual(resolveInitialVersions(), []);

  // The server explains a non-ready layer better than we can: it knows which
  // workflow the model came from.
  assert.equal(
    resolveReadinessDetail({
      predictionsReadiness: { ready: false, detail: "Preparing tiles." },
    }),
    "Preparing tiles."
  );
  assert.equal(resolveReadinessDetail({ predictionsReadiness: {} }), "");
  assert.equal(resolveReadinessDetail({}), "");
  assert.equal(resolveReadinessDetail(), "");
});

test("footprint status never reports an empty map as ready", () => {
  // A model with zero predicted buildings is EMPTY whatever else is true —
  // no job will ever produce footprints for it.
  assert.equal(
    resolveFootprintStatus({ loaded: true, buildingCount: 0 }),
    FOOTPRINTS_EMPTY
  );
  assert.equal(
    resolveFootprintStatus({ error: "boom", buildingCount: 0 }),
    FOOTPRINTS_EMPTY
  );

  assert.equal(
    resolveFootprintStatus({ loaded: true, error: "boom" }),
    FOOTPRINTS_UNAVAILABLE
  );
  assert.equal(resolveFootprintStatus({ loaded: true }), FOOTPRINTS_READY);
  assert.equal(
    resolveFootprintStatus({ loading: true, ready: false }),
    FOOTPRINTS_PREPARING,
    "a known-missing artifact is preparing, not loading"
  );
  assert.equal(resolveFootprintStatus({ loading: true }), FOOTPRINTS_LOADING);
  assert.equal(resolveFootprintStatus({}), FOOTPRINTS_LOADING);
  assert.equal(resolveFootprintStatus(), FOOTPRINTS_LOADING);

  // Only a fully loaded vector layer can be edited.
  assert.equal(canEditFootprints(FOOTPRINTS_READY), true);
  for (const status of [
    FOOTPRINTS_LOADING,
    FOOTPRINTS_PREPARING,
    FOOTPRINTS_EMPTY,
    FOOTPRINTS_UNAVAILABLE,
    undefined,
  ]) {
    assert.equal(canEditFootprints(status), false);
  }
});

test("the server's readiness reason separates 'not yet' from 'never'", () => {
  // Only "preparing" is something a tiling job can fix. The others must not
  // be dressed up as "nearly there" — the user has to go and do something
  // else, and the server's `detail` already says what.
  assert.equal(
    statusForReadinessReason("preparing"),
    FOOTPRINTS_PREPARING
  );
  assert.equal(
    statusForReadinessReason("not_processed"),
    FOOTPRINTS_UNAVAILABLE
  );
  assert.equal(
    statusForReadinessReason("no_predictions"),
    FOOTPRINTS_UNAVAILABLE
  );
  assert.equal(statusForReadinessReason("no_buildings"), FOOTPRINTS_EMPTY);
  // "ready" says nothing on its own: the payload was written before the
  // browser tried to download anything.
  assert.equal(statusForReadinessReason("ready"), null);
  assert.equal(statusForReadinessReason(""), null);
  assert.equal(statusForReadinessReason(), null);
  assert.equal(statusForReadinessReason("something new"), null);

  assert.equal(
    resolveReadinessReason({ predictionsReadiness: { reason: "preparing" } }),
    "preparing"
  );
  assert.equal(resolveReadinessReason({ predictionsReadiness: {} }), "");
  assert.equal(resolveReadinessReason(), "");

  // A job is queued unless the server has ruled one out. An unknown reason
  // still queues — that is the pre-contract behaviour, and it is harmless.
  assert.equal(shouldRequestPreparation("preparing"), true);
  assert.equal(shouldRequestPreparation("ready"), true);
  assert.equal(shouldRequestPreparation(""), true);
  assert.equal(shouldRequestPreparation(), true);
  assert.equal(shouldRequestPreparation("not_processed"), false);
  assert.equal(shouldRequestPreparation("no_predictions"), false);
  assert.equal(shouldRequestPreparation("no_buildings"), false);
});

test("a declared reason outranks a guess, but never a loaded map", () => {
  // Without the reason, a missing artifact reads as "preparing" forever on a
  // model that was never processed.
  assert.equal(
    resolveFootprintStatus({ ready: false, reason: "not_processed" }),
    FOOTPRINTS_UNAVAILABLE
  );
  assert.equal(
    resolveFootprintStatus({ ready: false, reason: "no_buildings" }),
    FOOTPRINTS_EMPTY
  );
  assert.equal(
    resolveFootprintStatus({ loading: true, reason: "preparing" }),
    FOOTPRINTS_PREPARING
  );
  // Footprints actually on the map beat a stale payload.
  assert.equal(
    resolveFootprintStatus({ loaded: true, reason: "not_processed" }),
    FOOTPRINTS_READY
  );
  // As does a real load failure, which carries a more specific message.
  assert.equal(
    resolveFootprintStatus({ error: "boom", reason: "preparing" }),
    FOOTPRINTS_UNAVAILABLE
  );
  // An unrecognised reason falls through to the artifact flags.
  assert.equal(
    resolveFootprintStatus({ ready: false, reason: "ready" }),
    FOOTPRINTS_PREPARING
  );
  assert.equal(
    resolveFootprintStatus({ loading: true, reason: "brand new reason" }),
    FOOTPRINTS_LOADING
  );
});

test("the map always says which version it is drawing", () => {
  assert.equal(resolveActiveVersion({ predictionVersion: 3 }), 3);
  assert.equal(resolveActiveVersion({ predictionVersion: "2" }), 2);
  // version=0 forces the model's raw output, so it is not a version.
  assert.equal(resolveActiveVersion({ predictionVersion: 0 }), null);
  assert.equal(resolveActiveVersion({ predictionVersion: null }), null);
  assert.equal(resolveActiveVersion({ predictionVersion: "" }), null);
  assert.equal(resolveActiveVersion({ predictionVersion: "latest" }), null);
  assert.equal(resolveActiveVersion({}), null);
  assert.equal(resolveActiveVersion(), null);

  assert.match(describeServedVersion(3), /version 3/);
  assert.match(describeServedVersion(null), /model/i);
  assert.match(describeServedVersion(), /model/i);
});

test("every non-ready status explains itself", () => {
  assert.equal(describeFootprintStatus(FOOTPRINTS_READY), null);

  for (const status of [
    FOOTPRINTS_LOADING,
    FOOTPRINTS_PREPARING,
    FOOTPRINTS_EMPTY,
    FOOTPRINTS_UNAVAILABLE,
  ]) {
    const message = describeFootprintStatus(status);
    assert.ok(message.title.length > 0, `${status} needs a title`);
    assert.ok(message.body.length > 0, `${status} needs a body`);
    assert.ok(["info", "warning", "error"].includes(message.intent));
  }

  // The job's own status message beats the generic copy when we have one.
  assert.equal(
    describeFootprintStatus(FOOTPRINTS_PREPARING, { detail: "Tiling 12%" }).body,
    "Tiling 12%"
  );
  assert.equal(
    describeFootprintStatus(FOOTPRINTS_UNAVAILABLE, { detail: "HTTP 500" }).body,
    "HTTP 500"
  );

  // The pencil's tooltip has to say why it is disabled.
  assert.match(describeEditAvailability(FOOTPRINTS_READY), /Edit/);
  assert.match(describeEditAvailability(FOOTPRINTS_EMPTY), /no per-building/);
  assert.match(describeEditAvailability(FOOTPRINTS_PREPARING), /preparing/);
  assert.match(describeEditAvailability(FOOTPRINTS_UNAVAILABLE), /could not be loaded/);
  assert.match(describeEditAvailability(FOOTPRINTS_LOADING), /Loading/);
});

test("the layer list never offers a toggle for a layer that is not there", () => {
  const inference = visualizerLayerOptions({
    results: {
      predictedDamageLayer: { url: "https://titiler/a?url=abfs://v.tif" },
      predictionsLayer: { url: "https://titiler/b?url=abfs://p.tif" },
    },
    footprintStatus: FOOTPRINTS_READY,
  });
  assert.deepEqual(
    inference.map((option) => option.key),
    ["predictedDamageLayer", "predictionsLayer", "footprints"]
  );
  assert.ok(inference.every((option) => option.disabled === false));

  // The embedding workflow: footprints are the only layer there is.
  const embedding = visualizerLayerOptions({
    results: { predictedDamageLayer: null, predictionsLayer: null },
    footprintStatus: FOOTPRINTS_READY,
  });
  assert.deepEqual(
    embedding.map((option) => option.key),
    ["footprints"]
  );

  // Footprints are always listed, but cannot be toggled before they exist.
  const preparing = visualizerLayerOptions({
    results: {},
    footprintStatus: FOOTPRINTS_PREPARING,
  });
  assert.deepEqual(preparing.map((option) => option.key), ["footprints"]);
  assert.equal(preparing[0].disabled, true);
  assert.equal(visualizerLayerOptions().length, 1);
  assert.ok(visualizerLayerOptions().every((option) => option.label.length > 0));
});

test("unsaved edits are measured against the last saved version", () => {
  assert.equal(sameOverrides({}, {}), true);
  assert.equal(sameOverrides(null, undefined), true);
  assert.equal(sameOverrides({ 1: CLASS_DAMAGED }, { 1: CLASS_DAMAGED }), true);
  assert.equal(sameOverrides({ 1: CLASS_DAMAGED }, { 1: CLASS_UNKNOWN }), false);
  assert.equal(sameOverrides({ 1: CLASS_DAMAGED }, {}), false);
  assert.equal(sameOverrides({}, { 1: CLASS_DAMAGED }), false);

  // No baseline yet: any override at all is unsaved work.
  assert.equal(hasUnsavedEdits({ overrides: {} }), false);
  assert.equal(hasUnsavedEdits({ overrides: { 3: CLASS_DAMAGED } }), true);

  // Saving establishes a baseline, so the edits it wrote stop counting.
  const baseline = {
    threshold: 0.5,
    unknownThreshold: 0.5,
    overrides: { 3: CLASS_DAMAGED },
  };
  assert.equal(
    hasUnsavedEdits({
      overrides: { 3: CLASS_DAMAGED },
      threshold: 0.5,
      unknownThreshold: 0.5,
      baseline,
    }),
    false
  );
  assert.equal(
    hasUnsavedEdits({
      overrides: { 3: CLASS_DAMAGED, 4: CLASS_UNKNOWN },
      threshold: 0.5,
      unknownThreshold: 0.5,
      baseline,
    }),
    true
  );
  // Moving a threshold is unsaved work too — it reclassifies every building.
  assert.equal(
    hasUnsavedEdits({
      overrides: { 3: CLASS_DAMAGED },
      threshold: 0.6,
      unknownThreshold: 0.5,
      baseline,
    }),
    true
  );
  assert.equal(
    hasUnsavedEdits({
      overrides: { 3: CLASS_DAMAGED },
      threshold: 0.5,
      unknownThreshold: 0.25,
      baseline,
    }),
    true
  );

  // Added, changed and removed overrides all count once each.
  assert.equal(countUnsavedOverrides({ 3: CLASS_DAMAGED }, baseline), 0);
  assert.equal(
    countUnsavedOverrides({ 3: CLASS_UNKNOWN }, baseline),
    1,
    "changed"
  );
  assert.equal(
    countUnsavedOverrides({ 3: CLASS_DAMAGED, 4: CLASS_DAMAGED }, baseline),
    1,
    "added"
  );
  assert.equal(countUnsavedOverrides({}, baseline), 1, "removed");
  assert.equal(countUnsavedOverrides({ 1: CLASS_DAMAGED }, null), 1);
  assert.equal(countUnsavedOverrides(null, null), 0);

  assert.match(describeUnsavedEdits({ 1: CLASS_DAMAGED }, null), /^1 building /);
  assert.match(
    describeUnsavedEdits({ 1: CLASS_DAMAGED, 2: CLASS_UNKNOWN }, null),
    /^2 buildings /
  );
  // Thresholds moved but nothing clicked: still worth warning about.
  assert.match(describeUnsavedEdits({}, null), /threshold changes/);
});

// ── Footprint renderer helpers (predictionFootprintMap.js) ──────────────────

test("class codes are stable and unknown classes never collide with them", () => {
  assert.equal(PMTILES_SOURCE_LAYER, "buildings");
  assert.equal(classCode(CLASS_DAMAGED), CLASS_CODES[CLASS_DAMAGED]);
  assert.equal(classCode(CLASS_NOT_DAMAGED), CLASS_CODES[CLASS_NOT_DAMAGED]);
  assert.equal(classCode(CLASS_UNKNOWN), CLASS_CODES[CLASS_UNKNOWN]);
  const codes = Object.values(CLASS_CODES);
  assert.equal(new Set(codes).size, codes.length, "codes must be distinct");
  assert.ok(codes.every((code) => code > 0), "0 is reserved for unclassified");

  // A footprint whose tile arrived before its scores did.
  assert.equal(classCode(undefined), 0);
  assert.equal(classCode("something-else"), 0);

  assert.deepEqual(footprintFeatureState({ cls: CLASS_DAMAGED }), {
    cls: CLASS_CODES[CLASS_DAMAGED],
    dim: false,
    edited: false,
    selected: false,
  });
  assert.deepEqual(
    footprintFeatureState({
      cls: CLASS_UNKNOWN,
      dim: 1,
      edited: "yes",
      selected: true,
    }),
    {
      cls: CLASS_CODES[CLASS_UNKNOWN],
      dim: true,
      edited: true,
      selected: true,
    }
  );
  assert.deepEqual(footprintFeatureState(), {
    cls: 0,
    dim: false,
    edited: false,
    selected: false,
  });
});

test("paint expressions key off feature-state so recolouring needs no reload", () => {
  const colors = {
    damaged: "#111111",
    notDamaged: "#222222",
    unknown: "#333333",
    pending: "#444444",
    outline: "#555555",
    edited: "#666666",
    selected: "#777777",
  };

  const fill = fillColorExpression(colors);
  assert.equal(fill[0], "case");
  assert.deepEqual(fill[1], [
    "==",
    ["feature-state", "cls"],
    CLASS_CODES[CLASS_DAMAGED],
  ]);
  assert.equal(fill[2], colors.damaged);
  assert.equal(fill[4], colors.notDamaged);
  assert.equal(fill[6], colors.unknown);
  assert.equal(fill.at(-1), colors.pending, "unclassified is the default arm");

  const stroke = strokeColorExpression(colors);
  assert.equal(stroke[0], "case");
  assert.equal(stroke[2], colors.selected, "selection outranks edited");
  assert.equal(stroke[4], colors.edited);
  assert.equal(stroke.at(-1), colors.outline);

  // Never hand the renderer an undefined colour: it drops the whole layer.
  assert.deepEqual(fillColorExpression(null), fillColorExpression(FALLBACK_COLORS));
  assert.deepEqual(
    strokeColorExpression(undefined),
    strokeColorExpression(FALLBACK_COLORS)
  );

  // Filtered-out buildings stay on screen as context, but faint.
  assert.equal(FILL_OPACITY_EXPRESSION[0], "case");
  assert.ok(FILL_OPACITY_EXPRESSION[2] < FILL_OPACITY_EXPRESSION[3]);
});

test("map colours come from the theme, with a parseable last resort", () => {
  const tokenMap = {
    damaged: "var(--colorStatusDangerBackground3)",
    notDamaged: "var(--colorStatusSuccessBackground3)",
    unknown: "var(--colorNeutralForeground3)",
    pending: "var(--colorNeutralBackground5)",
    outline: "var(--colorNeutralStrokeAccessible)",
    edited: "var(--colorBrandStroke1)",
    selected: "var(--colorNeutralForeground1)",
  };
  const resolved = resolveMapColors(tokenMap, (name) => ` value-for${name} `);
  assert.equal(resolved.damaged, "value-for--colorStatusDangerBackground3");
  assert.equal(resolved.selected, "value-for--colorNeutralForeground1");

  // A token the theme cannot answer for, a lookup that throws, and no lookup
  // at all must all still paint something.
  assert.deepEqual(resolveMapColors(tokenMap, () => ""), FALLBACK_COLORS);
  assert.deepEqual(
    resolveMapColors(tokenMap, () => {
      throw new Error("no such property");
    }),
    FALLBACK_COLORS
  );
  assert.deepEqual(resolveMapColors(tokenMap, null), FALLBACK_COLORS);
  assert.deepEqual(resolveMapColors(null, () => "#abcdef"), FALLBACK_COLORS);
  // A v9 token is "var(--x)"; handing the raw string to the renderer would
  // fail, so anything that is not a var() reference falls back too.
  assert.deepEqual(
    resolveMapColors({ damaged: "#123456" }, () => "#abcdef").damaged,
    FALLBACK_COLORS.damaged
  );

  // Outside a browser there is no computed style to read.
  assert.equal(themeColorLookup(null)("--x"), "");
  assert.equal(themeColorLookup({})("--x"), "");
});

test("the renderer under atlas.Map is duck-typed, never assumed", () => {
  const gl = { setFeatureState() {} };
  assert.equal(findGlMap({ map: gl }), gl);
  assert.equal(findGlMap({ _map: gl }), gl);
  assert.equal(findGlMap({ gl }), gl);
  assert.equal(findGlMap({ _gl: gl }), gl);
  // A build that renamed the property is still found by scanning.
  assert.equal(findGlMap({ somethingElse: gl }), gl);

  assert.equal(findGlMap(null), null);
  assert.equal(findGlMap(undefined), null);
  assert.equal(findGlMap("map"), null);
  assert.equal(findGlMap({ map: {} }), null);
});

test("source and layer ids are discovered because Azure Maps renames them", () => {
  const glMap = {
    getStyle: () => ({
      sources: {
        "vectorTiles-0": { type: "vector" },
        "predictedBuildings-3": { type: "vector" },
        basemap: { type: "raster" },
      },
      layers: [
        { id: "basemapFill", type: "fill", source: "basemap" },
        { id: "predictedBuildingsFill-3", type: "fill", source: "predictedBuildings-3" },
        { id: "unrelatedLine", type: "line", source: "predictedBuildings-3" },
      ],
    }),
  };

  assert.deepEqual(
    discoverFillLayerIds(
      glMap,
      ["visualizerPrimaryFootprintFill"],
      ["visualizerPrimaryBuildings"]
    ),
    ["predictedBuildingsFill-3"],
    "the basemap's own fill layers are not ours to click"
  );
  // Nothing to discover: keep the ids we asked for.
  assert.deepEqual(
    discoverFillLayerIds({ getStyle: () => ({}) }, ["fallbackFill"]),
    ["fallbackFill"]
  );
  assert.deepEqual(discoverFillLayerIds(null, ["fallbackFill"]), ["fallbackFill"]);
  assert.deepEqual(discoverFillLayerIds(null, null), []);
  // A renderer that throws must not take the layer down with it.
  assert.deepEqual(
    discoverFillLayerIds(
      {
        getStyle: () => {
          throw new Error("style not loaded");
        },
      },
      ["fallbackFill"]
    ),
    ["fallbackFill"]
  );

  assert.equal(
    discoverVectorSourceId(glMap, "visualizerPrimaryBuildings"),
    "predictedBuildings-3"
  );
  // Our own id survived: use it.
  assert.equal(
    discoverVectorSourceId(
      { getStyle: () => ({ sources: { mySource: { type: "vector" } } }) },
      "mySource"
    ),
    "mySource"
  );
  assert.equal(discoverVectorSourceId(null, "mySource"), "mySource");
  assert.equal(
    discoverVectorSourceId(
      {
        getStyle: () => {
          throw new Error("style not loaded");
        },
      },
      "mySource"
    ),
    "mySource"
  );
});

test("centroids and drag rectangles survive the shapes the map hands over", () => {
  assert.deepEqual(
    featureCentroid({
      type: "Polygon",
      coordinates: [[[0, 0], [0, 2], [2, 2], [2, 0]]],
    }),
    [1, 1]
  );
  assert.deepEqual(
    featureCentroid({
      type: "MultiPolygon",
      coordinates: [[[[0, 0], [0, 4], [4, 4], [4, 0]]]],
    }),
    [2, 2]
  );
  assert.equal(featureCentroid(null), null);
  assert.equal(featureCentroid({ type: "Point", coordinates: [1, 2] }), null);
  assert.equal(featureCentroid({ type: "Polygon", coordinates: [[]] }), null);
  assert.equal(featureCentroid({ type: "Polygon", coordinates: [[[0]]] }), null);

  // Dragged up-and-left: the box still has its top-left corner first.
  assert.deepEqual(
    normalizeSelectionBox({ x: 100, y: 100 }, { x: 20, y: 30 }),
    { x1: 20, y1: 30, x2: 100, y2: 100 }
  );
  assert.deepEqual(
    normalizeSelectionBox({ x: 20, y: 30 }, { x: 100, y: 100 }),
    { x1: 20, y1: 30, x2: 100, y2: 100 }
  );
  // Too small to be deliberate: that was a click, not a box-select.
  assert.equal(normalizeSelectionBox({ x: 10, y: 10 }, { x: 12, y: 40 }), null);
  assert.equal(normalizeSelectionBox({ x: 10, y: 10 }, { x: 40, y: 12 }), null);
  assert.deepEqual(
    normalizeSelectionBox({ x: 10, y: 10 }, { x: 12, y: 12 }, 1),
    { x1: 10, y1: 10, x2: 12, y2: 12 }
  );
  assert.equal(normalizeSelectionBox(null, { x: 1, y: 1 }), null);
  assert.equal(normalizeSelectionBox({ x: 1, y: 1 }, null), null);
});

// ── Version sidecars ────────────────────────────────────────────────────────
// A saved version's sidecar is the raw shape plus `classes`: the class each
// building was saved with. The model's `damage` / `unknown` fractions are
// left untouched beside them, so anything that re-derives a class from those
// fractions would silently undo the analyst's edit.

// The same five buildings as sampleAttrs(), saved as a version in which two
// were corrected by hand: #11 (0.5, would derive NotDamaged) was marked
// Damaged, and #13 (0.9, would derive Damaged) was marked NotDamaged.
function versionAttrs() {
  return normalizeAttrs({
    n: 5,
    ids: [10, 11, 12, 13, 14],
    overtureIds: ["a", "b", "c", "d", "e"],
    damage: [0.05, 0.5, 0.51, 0.9, 0.8],
    unknown: [0, 0, 0, 0, 0.4],
    damaged: [0, 1, 1, 0, 0],
    classes: [
      CLASS_NOT_DAMAGED,
      CLASS_DAMAGED,
      CLASS_DAMAGED,
      CLASS_NOT_DAMAGED,
      CLASS_UNKNOWN,
    ],
  });
}

test("normalizeAttrs keeps a version's saved classes and drops malformed ones", () => {
  const attrs = versionAttrs();
  assert.equal(attrs.classes.length, 5);
  assert.equal(attrs.classes[1], CLASS_DAMAGED);

  // The raw model's sidecar has no classes at all — not an absent array the
  // rest of the code has to guard against.
  assert.deepEqual(sampleAttrs().classes, []);
  assert.deepEqual(normalizeAttrs({ ids: [1], classes: "Damaged" }).classes, []);

  // A row the server could not classify must fall back to the derived class
  // rather than poisoning it with a value nothing understands.
  const messy = normalizeAttrs({
    n: 3,
    ids: [1, 2, 3],
    damage: [0.9, 0.9, 0.9],
    classes: ["Damaged", "Rubble", null],
  });
  assert.deepEqual(messy.classes, [CLASS_DAMAGED, null, null]);
});

test("savedClassAt and hasSavedClasses tell a version's sidecar from the raw one", () => {
  const attrs = versionAttrs();
  assert.equal(savedClassAt(attrs, 1), CLASS_DAMAGED);
  assert.equal(savedClassAt(attrs, 99), null);
  assert.equal(savedClassAt(null, 0), null);
  assert.equal(hasSavedClasses(attrs), true);

  assert.equal(hasSavedClasses(sampleAttrs()), false);
  assert.equal(hasSavedClasses(null), false);
  // Present but useless: nothing to preserve, so the thresholds still apply.
  assert.equal(
    hasSavedClasses(normalizeAttrs({ n: 2, ids: [1, 2], classes: [null, "x"] })),
    false
  );
});

test("baseClassAt prefers a saved class over the thresholds", () => {
  const attrs = versionAttrs();
  // Saved NotDamaged at 0.9 damage: the threshold says otherwise and loses.
  assert.equal(baseClassAt(attrs, 3, 0.5), CLASS_NOT_DAMAGED);
  // Saved Damaged at exactly the threshold, where derivation says NotDamaged.
  assert.equal(baseClassAt(attrs, 1, 0.5), CLASS_DAMAGED);
  // Moving the slider cannot shift a saved class either.
  assert.equal(baseClassAt(attrs, 3, 0.99), CLASS_NOT_DAMAGED);
  // The raw sidecar has nothing saved, so the threshold decides.
  assert.equal(baseClassAt(sampleAttrs(), 3, 0.5), CLASS_DAMAGED);
});

test("classifyAll colours an edited version from its saved classes", () => {
  const attrs = versionAttrs();
  const result = classifyAll(attrs, { threshold: 0.5, unknownThreshold: 0.3 });
  assert.deepEqual(result.classes, [
    CLASS_NOT_DAMAGED,
    CLASS_DAMAGED,
    CLASS_DAMAGED,
    CLASS_NOT_DAMAGED,
    CLASS_UNKNOWN,
  ]);
  // Saved classes are not "edited" in this session: nothing is pending.
  assert.equal(result.editedCount, 0);
  assert.deepEqual(result.edited, [false, false, false, false, false]);
  assert.equal(result.counts[CLASS_DAMAGED], 2);

  // A fresh edit in this session still wins over the saved class.
  const edited = classifyAll(attrs, {
    threshold: 0.5,
    overrides: { 13: CLASS_DAMAGED },
  });
  assert.equal(edited.classes[3], CLASS_DAMAGED);
  assert.equal(edited.editedCount, 1);
  assert.equal(resolveClassAt(attrs, 3, { threshold: 0.5 }), CLASS_NOT_DAMAGED);
});

test("countClassChanges ignores buildings a version already decided", () => {
  const attrs = versionAttrs();
  // Every row has a saved class, so no slider move can flip anything.
  assert.equal(
    countClassChanges(attrs, { threshold: 0.5 }, { threshold: 0.95 }),
    0
  );
  // The same move on the raw sidecar does flip buildings, which is what makes
  // the readout worth showing there.
  assert.ok(
    countClassChanges(sampleAttrs(), { threshold: 0.5 }, { threshold: 0.95 }) > 0
  );
});

test("mergedOverrideList carries the classes the thresholds cannot reproduce", () => {
  const attrs = versionAttrs();
  // At 0.5 the raw scores would derive NotDamaged, Damaged, Damaged for rows
  // 1/3/4 differently from what was saved, so exactly those travel.
  assert.deepEqual(mergedOverrideList(attrs, {}, 0.5, 0.3), [
    { id: 11, class: CLASS_DAMAGED },
    { id: 13, class: CLASS_NOT_DAMAGED },
  ]);
  // Row 14's saved Unknown IS reproducible at unknownThreshold 0.3, so it is
  // not sent; drop the unknown threshold and it has to be.
  assert.deepEqual(mergedOverrideList(attrs, {}, 0.5, 0.9), [
    { id: 11, class: CLASS_DAMAGED },
    { id: 13, class: CLASS_NOT_DAMAGED },
    { id: 14, class: CLASS_UNKNOWN },
  ]);
  // A fresh edit replaces the carried-over class rather than duplicating it.
  assert.deepEqual(mergedOverrideList(attrs, { 13: CLASS_UNKNOWN }, 0.5, 0.3), [
    { id: 11, class: CLASS_DAMAGED },
    { id: 13, class: CLASS_UNKNOWN },
  ]);
  // The raw sidecar has nothing to carry: only the user's own edits go.
  assert.deepEqual(
    mergedOverrideList(sampleAttrs(), { 10: CLASS_DAMAGED }, 0.5, 0),
    [{ id: 10, class: CLASS_DAMAGED }]
  );
  assert.deepEqual(mergedOverrideList(null, null, 0.5, 0), []);
});

test("buildSavePayload carries a version's classes into the next version", () => {
  const attrs = versionAttrs();
  // The server derives every new version from the RAW GeoPackage, so saving
  // an edit on top of version N must re-state what N established.
  const payload = buildSavePayload({
    projectId: "p",
    imageLayerId: "l",
    modelId: "m",
    threshold: 0.5,
    unknownThreshold: 0.3,
    overrides: { 10: CLASS_UNKNOWN },
    attrs,
  });
  assert.deepEqual(payload.overrides, [
    { id: 10, class: CLASS_UNKNOWN },
    { id: 11, class: CLASS_DAMAGED },
    { id: 13, class: CLASS_NOT_DAMAGED },
  ]);
  assert.equal(payload.threshold, 0.5);

  // Editing the raw output is unchanged: no attrs, no carried-over classes.
  assert.deepEqual(
    buildSavePayload({
      projectId: "p",
      imageLayerId: "l",
      modelId: "m",
      threshold: 0.5,
      unknownThreshold: 0,
      overrides: { 12: CLASS_UNKNOWN },
    }).overrides,
    [{ id: 12, class: CLASS_UNKNOWN }]
  );
});

// ── Version-pinned artifacts ────────────────────────────────────────────────

test("normalizeVersionParam keeps the raw output's explicit zero", () => {
  assert.equal(normalizeVersionParam(0), 0);
  assert.equal(normalizeVersionParam("0"), 0);
  assert.equal(normalizeVersionParam(3), 3);
  assert.equal(normalizeVersionParam("3"), 3);
  assert.equal(normalizeVersionParam(3.7), 3);
  // "Say nothing and let the route apply its own default."
  assert.equal(normalizeVersionParam(null), null);
  assert.equal(normalizeVersionParam(undefined), null);
  assert.equal(normalizeVersionParam(""), null);
  // The route 400s on these, so they never leave the browser.
  assert.equal(normalizeVersionParam(-1), null);
  assert.equal(normalizeVersionParam("latest"), null);
  assert.equal(normalizeVersionParam(NaN), null);
});

test("buildArtifactUrl pins a version only when there is one to pin", () => {
  assert.equal(
    buildArtifactUrl({ projectId: "p", modelId: "m", kind: "gpkg" }),
    "GetModelArtifact?projectId=p&modelId=m&kind=gpkg"
  );
  assert.equal(
    buildArtifactUrl({ projectId: "p", modelId: "m", kind: "gpkg", version: 2 }),
    "GetModelArtifact?projectId=p&modelId=m&kind=gpkg&version=2"
  );
  // Zero is a real request — "the raw output, explicitly" — not an absence.
  assert.equal(
    buildArtifactUrl({ projectId: "p", modelId: "m", kind: "gpkg", version: 0 }),
    "GetModelArtifact?projectId=p&modelId=m&kind=gpkg&version=0"
  );
  assert.equal(
    buildArtifactUrl({
      projectId: "p",
      modelId: "m",
      kind: "gpkg",
      version: null,
    }),
    "GetModelArtifact?projectId=p&modelId=m&kind=gpkg"
  );
});

test("resolvePredictionArtifacts never substitutes the raw sidecar for a version", () => {
  const ids = { projectId: "p", imageLayerId: "l", modelId: "m" };

  // The server named the artifacts: use exactly what it said.
  const served = resolvePredictionArtifacts(
    {
      predictionVersion: 2,
      footprintTilesUrl: "tiles",
      predictionAttrsUrl: "attrs?version=2",
    },
    ids
  );
  assert.equal(served.predictionAttrsUrl, "attrs?version=2");
  assert.equal(served.version, 2);

  // It did not, and the payload was served for version 2 — so the
  // reconstructed endpoint is pinned to 2 rather than falling back to the raw
  // sidecar, which describes the model's classes and not the analyst's.
  const reconstructed = resolvePredictionArtifacts(
    { predictionVersion: 2 },
    ids
  );
  assert.ok(reconstructed.predictionAttrsUrl.includes("kind=prediction_attrs"));
  assert.ok(reconstructed.predictionAttrsUrl.endsWith("&version=2"));
  // The geometry is shared by every version, so the tiles are never pinned.
  assert.ok(!reconstructed.footprintTilesUrl.includes("version"));

  // Raw output: no version segment at all.
  const raw = resolvePredictionArtifacts({}, ids);
  assert.ok(!raw.predictionAttrsUrl.includes("version"));
  assert.equal(raw.version, null);
});

test("resolveVersionIsLatest trusts the server's flag", () => {
  // Absent means "assume newest", which is what omitting `version` has always
  // meant — an older backend must not read as a divergence.
  assert.equal(resolveVersionIsLatest({}), true);
  assert.equal(resolveVersionIsLatest(null), true);
  assert.equal(resolveVersionIsLatest({ predictionVersionIsLatest: true }), true);
  assert.equal(
    resolveVersionIsLatest({ predictionVersionIsLatest: false }),
    false
  );
});

test("versionSidecarPending only fires for a version the server says is not ready", () => {
  // Version selected, no sidecar, server says it is being prepared.
  assert.equal(
    versionSidecarPending({
      predictionVersion: 2,
      predictionsReadiness: { attrsReady: false, reason: "preparing" },
    }),
    true
  );
  assert.equal(
    versionSidecarPending({ predictionVersion: 2, predictionsReady: false }),
    true
  );
  // The sidecar is there: nothing pending, whatever else the payload says.
  assert.equal(
    versionSidecarPending({
      predictionVersion: 2,
      predictionAttrsUrl: "attrs?version=2",
      predictionsReady: false,
    }),
    false
  );
  // The raw output is never "a version waiting to be backfilled".
  assert.equal(versionSidecarPending({ predictionsReady: false }), false);
  assert.equal(versionSidecarPending({ predictionVersion: 2 }), false);
  assert.equal(versionSidecarPending(null), false);
});

test("prep responses carry the version backfill queue onto the session", () => {
  const session = applyPrepResponse(
    { tilesReady: false, attrsReady: false },
    { predictionTilesStatus: "InProgress", versionsPending: 3 }
  );
  assert.equal(session.versionsPending, 3);
  assert.equal(describePendingVersions(session), "Rebuilding 3 saved versions.");
  assert.equal(
    describePendingVersions({ versionsPending: 1 }),
    "Rebuilding 1 saved version."
  );
  // Nothing outstanding, or a backend that never said: say nothing.
  assert.equal(describePendingVersions({ versionsPending: 0 }), "");
  assert.equal(describePendingVersions({}), "");
  assert.equal(describePendingVersions(null), "");
  assert.equal(
    applyPrepResponse({ tilesReady: false }, { versionsPending: "nope" })
      .versionsPending,
    undefined
  );
});

// ── Version selection ───────────────────────────────────────────────────────

test("version selections normalise to an integer, raw output included", () => {
  assert.equal(normalizeVersionSelection(2), 2);
  assert.equal(normalizeVersionSelection("2"), 2);
  assert.equal(normalizeVersionSelection(0), RAW_VERSION);
  assert.equal(normalizeVersionSelection(null), RAW_VERSION);
  assert.equal(normalizeVersionSelection(-4), RAW_VERSION);
  assert.equal(versionKey(2), "2");
  assert.equal(versionKey(null), "0");
  assert.equal(versionLabel(3), "Version 3");
  assert.equal(versionLabel(null), RAW_VERSION_LABEL);
  assert.equal(describeVersionInline(3), "edited version 3");
  assert.equal(describeVersionInline(0), "the model's own predictions");
});

test("isVersionReady is about the sidecar, not the version's existence", () => {
  assert.equal(isVersionReady({ version: 2, predictionAttrsUrl: "a" }), true);
  // Saved, but nothing to draw yet: offering it would produce an empty map.
  assert.equal(isVersionReady({ version: 2, predictionAttrsUrl: null }), false);
  assert.equal(isVersionReady({ version: 2, predictionAttrsUrl: "  " }), false);
  assert.equal(isVersionReady({ version: 2 }), false);
  assert.equal(isVersionReady(null), false);
});

test("buildVisualizerResultsUrl asks for one version at a time", () => {
  const ids = { projectId: "p", imageLayerId: "l", modelId: "m" };
  // No version: the API applies its own default, the newest saved state.
  assert.equal(
    buildVisualizerResultsUrl(ids),
    "GetVisualizerResults?projectId=p&imageLayerId=l&modelId=m"
  );
  assert.equal(
    buildVisualizerResultsUrl({ ...ids, version: 2 }),
    "GetVisualizerResults?projectId=p&imageLayerId=l&modelId=m&version=2"
  );
  // Dropping to the raw output is an explicit request, not an omission.
  assert.equal(
    buildVisualizerResultsUrl({ ...ids, version: RAW_VERSION }),
    "GetVisualizerResults?projectId=p&imageLayerId=l&modelId=m&version=0"
  );
});

test("version downloads go through the artifact route, never a SAS URL", () => {
  const ids = { projectId: "p", imageLayerId: "l", modelId: "m" };
  assert.equal(
    buildVersionGpkgUrl({ ...ids, version: 2 }),
    "GetModelArtifact?projectId=p&imageLayerId=l&modelId=m&kind=gpkg&version=2"
  );
  // The raw output is pinned explicitly so the file the analyst gets always
  // matches the option they picked.
  assert.equal(
    buildVersionGpkgUrl(ids),
    "GetModelArtifact?projectId=p&imageLayerId=l&modelId=m&kind=gpkg&version=0"
  );
  assert.match(describeVersionDownload(2), /version 2/);
  assert.match(describeVersionDownload(0), /model's own predictions/);
  assert.match(describeVersionDownload(2), /\.gpkg/);
});

test("the selector lists saved versions newest first with the raw output last", () => {
  const versions = [
    { version: 1, predictionAttrsUrl: "a1" },
    { version: 3, predictionAttrsUrl: null },
    { version: 2, predictionAttrsUrl: "a2" },
  ];
  const options = versionSelectorOptions({ versions, servedVersion: 2 });
  assert.deepEqual(
    options.map((option) => option.version),
    [3, 2, 1, RAW_VERSION]
  );

  // Version 3 is the newest but has no sidecar: offered, disabled, with the
  // reason attached rather than left to produce an empty map.
  assert.equal(options[0].disabled, true);
  assert.equal(options[0].isNewest, true);
  assert.equal(options[0].disabledReason, VERSION_PREPARING_REASON);
  assert.match(options[0].text, /preparing/);

  // Version 2 is what the map is drawing, and says so.
  assert.equal(options[1].disabled, false);
  assert.equal(options[1].isServed, true);
  assert.match(options[1].text, /on the map/);
  assert.equal(options[2].isServed, false);
  assert.equal(options[2].text, "Version 1");

  // The raw output is always selectable — it is the fallback when a version
  // cannot be drawn.
  assert.equal(options[3].isRaw, true);
  assert.equal(options[3].disabled, false);
  assert.equal(options[3].isNewest, false);
  assert.equal(options[3].text, RAW_VERSION_LABEL);
});

test("with nothing saved the selector offers only the raw output", () => {
  const options = versionSelectorOptions({ versions: [], servedVersion: null });
  assert.equal(options.length, 1);
  assert.equal(options[0].isRaw, true);
  assert.equal(options[0].isNewest, true);
  assert.equal(options[0].isServed, true);
  assert.match(options[0].text, /on the map/);
  // Junk in the version list is not offered as something to switch to.
  assert.deepEqual(
    versionSelectorOptions({
      versions: [{ version: 0 }, { version: null }, {}],
    }).map((option) => option.version),
    [RAW_VERSION]
  );
  assert.equal(versionSelectorOptions().length, 1);
});

test("the closed selector shows what is actually on the map", () => {
  const options = versionSelectorOptions({
    versions: [{ version: 1, predictionAttrsUrl: "a1" }],
    servedVersion: 1,
  });
  assert.equal(findVersionOption(options, 1).version, 1);
  assert.equal(findVersionOption(options, 9), null);
  assert.equal(findVersionOption(null, 1), null);
  assert.match(selectedVersionText(options, 1), /Version 1/);
  assert.match(selectedVersionText(options, 1), /on the map/);
  // A selection with no option (a version that vanished) still reads sanely.
  assert.equal(selectedVersionText(options, 9), "Version 9");
});

test("a version that is not the newest discloses the report divergence", () => {
  const versions = [{ version: 2 }, { version: 3 }];
  // The server says this is the newest: nothing to disclose.
  assert.equal(
    describeReportDivergence({ isLatest: true, servedVersion: 3, versions }),
    null
  );
  assert.equal(describeReportDivergence(), null);

  const note = describeReportDivergence({
    isLatest: false,
    servedVersion: 2,
    versions,
  });
  assert.match(note.title, /newest/i);
  assert.match(note.body, /edited version 2/);
  assert.match(note.body, /version 3/);
  assert.match(note.body, /Assessment and Validation/);

  // Sitting on the raw output while edits exist is the same disclosure.
  const rawNote = describeReportDivergence({
    isLatest: false,
    servedVersion: RAW_VERSION,
    versions,
  });
  assert.match(rawNote.body, /model's own predictions/);
});

test("a version with no sidecar explains itself and offers a way out", () => {
  const note = describeVersionSidecarPending({ version: 2, versionsPending: 2 });
  assert.match(note.title, /Version 2/);
  assert.match(note.body, /nothing to draw/);
  assert.match(note.body, /2 saved versions are waiting/);
  assert.match(note.body, /raw model output/);
  assert.match(
    describeVersionSidecarPending({ version: 2, versionsPending: 1 }).body,
    /1 saved version is waiting/
  );
  // The backend said nothing about a queue: do not invent one.
  assert.ok(
    !/waiting to be rebuilt/.test(
      describeVersionSidecarPending({ version: 2 }).body
    )
  );
});

test("a failed switch names what is still on the map", () => {
  const failure = describeVersionSwitchFailure({
    version: 2,
    shownVersion: 3,
    message: "The version could not be read from the server.",
  });
  assert.match(failure.title, /Version 2/);
  assert.match(failure.body, /could not be read/);
  // The point of the message: the previous version is still there, not a
  // blank map the analyst has to guess about.
  assert.match(failure.body, /still shows edited version 3/);
  assert.match(
    describeVersionSwitchFailure({ version: 1, shownVersion: RAW_VERSION }).body,
    /still shows the model's own predictions/
  );
});

test("switching away from unsaved edits says what will be lost", () => {
  const copy = describeVersionSwitchDiscard(2);
  assert.match(copy, /version 2/);
  assert.match(copy, /discards the edits you have not saved/);
  assert.match(copy, /Save them as a new version first/);

  // And an edited version's thresholds are inert, which is worth saying
  // rather than leaving a control silently missing.
  assert.match(describeSavedClassNote(2), /Version 2/);
  assert.match(describeSavedClassNote(2), /thresholds no longer apply/);
  assert.equal(describeSavedClassNote(RAW_VERSION), "");
});

test("the pending-version poll is bounded", () => {
  assert.equal(shouldPollVersionSidecar({ pending: true, attempt: 0 }), true);
  assert.equal(
    shouldPollVersionSidecar({
      pending: true,
      attempt: MAX_VERSION_POLL_ATTEMPTS - 1,
    }),
    true
  );
  // A forgotten tab stops asking instead of polling forever.
  assert.equal(
    shouldPollVersionSidecar({
      pending: true,
      attempt: MAX_VERSION_POLL_ATTEMPTS,
    }),
    false
  );
  assert.equal(shouldPollVersionSidecar({ pending: false, attempt: 0 }), false);
  assert.equal(shouldPollVersionSidecar(), false);
  assert.ok(VERSION_POLL_INTERVAL_MS >= 1000);
});
