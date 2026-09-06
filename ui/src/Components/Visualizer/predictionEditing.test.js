// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { normalizeAttrs } from "./predictionClassify.js";
import {
  buildSavePayload, canAdjustThresholds, classifyDraft, deriveClass, filteredRows,
  initialDraft, isDraftDirty, modelClassAt, nextReviewIndex, overrideList, saveAttempt,
  setOverrides, validateEditSession, countManualChanges, undoManualChanges,
} from "./predictionEditing.js";
import {
  buildVersionGpkgUrl, defaultPredictionVersion, predictionSourceOptions,
  validateSelectedSource, validateVersionManifest, versionEndpoint,
} from "./predictionVersions.js";
import { predictionRenderKey, visualizerSceneKey } from "./predictionResults.js";
import { requestPredictionJson, predictionErrorMessage } from "./predictionHttp.js";
import { publishPredictionEdit } from "./predictionEditWorkflow.js";
import { buildAssessmentSummary } from "../../util/assessmentSummary.js";

const ids = { projectId: "project", imageLayerId: "layer", modelId: "model" };
const source = {
  flavor: "inference", supportsThreshold: true, predictionRevision: "raw-generation",
  predictionVersion: 0, buildingCount: 3, defaultThreshold: 0, defaultUnknownThreshold: 0,
};
function rawAttrs() {
  return {
    schemaVersion: 1, predictionRevision: source.predictionRevision, flavor: "inference",
    n: 3, ids: [0, 1, 2], overtureIds: ["a", "b", "c"],
    damage: [0.6, 0.2, null], unknown: [0, 0, null], damaged: [1, 1, null],
    classes: ["Damaged", "Damaged", "Unknown"],
  };
}
function editedAttrs() {
  return {
    ...rawAttrs(), predictionVersion: 2, isEdited: true, threshold: 0.5, unknownThreshold: 0,
    classes: ["NotDamaged", "NotDamaged", "Damaged"],
    modelClasses: ["Damaged", "Damaged", "Unknown"],
    overrideClasses: ["NotDamaged", null, "Damaged"],
  };
}
function session(version = 0) {
  return {
    ...source, predictionVersion: version, currentPredictionRevision: source.predictionRevision,
    threshold: version ? 0.5 : 0, unknownThreshold: 0, editReadiness: { ready: true },
  };
}
const saved = {
  version: 3, predictionRevision: source.predictionRevision, buildingCount: 3, editedCount: 2,
  gpkgUrl: "GetModelArtifact?kind=gpkg&version=3",
  predictionAttrsUrl: "GetModelArtifact?kind=prediction_attrs&version=3",
};

test("raw classes do not imply editing; only raw standard models have sliders", () => {
  const attrs = normalizeAttrs(rawAttrs(), source);
  assert.equal(modelClassAt(attrs, 2), "Unknown");
  assert.equal(canAdjustThresholds(source), true);
  assert.equal(canAdjustThresholds({ ...source, flavor: "embedding", supportsThreshold: false }), false);
  assert.equal(canAdjustThresholds({ ...source, predictionVersion: 2 }), false);
  attrs.damage = [1, 0, null];
  assert.equal(canAdjustThresholds(source), true);
});

test("edited sidecars validate effective classes separately from null-score model baselines", () => {
  const attrs = normalizeAttrs(editedAttrs(), { ...source, predictionVersion: 2 });
  assert.equal(attrs.classes[2], "Damaged");
  assert.equal(attrs.modelClasses[2], "Unknown");
  assert.throws(() => normalizeAttrs(attrs, source), /versions differ/);
  assert.throws(() => normalizeAttrs({ ...attrs, modelClasses: ["Damaged", "Damaged", "Damaged"] }), /unscored row/);
  assert.throws(() => normalizeAttrs({ ...attrs, isEdited: false }), /provenance/);
  assert.throws(() => normalizeAttrs({ ...attrs, overrideClasses: [null] }), /exactly 3 rows/);
  assert.throws(() => normalizeAttrs({ ...attrs, overrideClasses: ["bad", null, "Damaged"] }), /invalid override/);
  assert.throws(() => normalizeAttrs({ ...attrs, overrideClasses: ["Damaged", null, "Damaged"] }), /override and effective/);
  assert.throws(() => normalizeAttrs({ ...rawAttrs(), isEdited: true }), /raw output/);
});

test("session must identify the exact displayed version, source generation and readiness", () => {
  assert.equal(validateEditSession(session(), source, rawAttrs()).predictionVersion, 0);
  for (const changes of [
    { predictionVersion: undefined, version: 0 }, { predictionVersion: 1 },
    { buildingCount: 4 }, { supportsThreshold: false },
  ]) assert.throws(() => validateEditSession({ ...session(), ...changes }, source, rawAttrs()), /does not match/);
  assert.throws(() => validateEditSession({ ...session(), editReadiness: { ready: false, detail: "Cannot edit" } }, source, rawAttrs()), /Cannot edit/);
  assert.throws(() => validateEditSession({ ...session(), currentPredictionRevision: "new" }, source, rawAttrs()), { code: "source_changed" });
  assert.throws(() => validateEditSession({ ...session(), predictionRevision: "new" }, source, rawAttrs()), { code: "source_changed" });
  assert.throws(() => validateEditSession({ ...session(), threshold: null }, source, rawAttrs()), /thresholds/);
});

test("saved draft preserves thresholds and the complete explicit assignment snapshot", () => {
  const attrs = editedAttrs();
  const draft = initialDraft(attrs, session(2));
  assert.equal(draft.threshold, 0.5);
  assert.deepEqual(overrideList(draft.overrides), [{ id: 0, class: "NotDamaged" }, { id: 2, class: "Damaged" }]);
  const payload = buildSavePayload(ids, { ...source, predictionVersion: 2 }, draft, "request-id");
  assert.equal(payload.baseVersion, 2);
  assert.equal(payload.predictionRevision, source.predictionRevision);
  assert.equal(payload.clientRequestId, "request-id");
  assert.deepEqual(payload.overrides, overrideList(draft.overrides));
});

test("right-click model reset is an explicit pin, even against different selected thresholds", () => {
  const attrs = editedAttrs();
  const baseline = initialDraft(attrs, session(2));
  const draft = {
    ...baseline,
    overrides: setOverrides(baseline.overrides, [1], modelClassAt(attrs, 1)),
  };
  assert.equal(deriveClass(attrs.damage[1], attrs.unknown[1], draft.threshold), "NotDamaged");
  assert.equal(draft.overrides[1], "Damaged");
  assert.deepEqual(overrideList(draft.overrides), [
    { id: 0, class: "NotDamaged" }, { id: 1, class: "Damaged" }, { id: 2, class: "Damaged" },
  ]);
  assert.equal(classifyDraft(attrs, { ...source, predictionVersion: 2 }, draft, baseline).classes[1], "Damaged");
  assert.equal(isDraftDirty(draft, baseline), true);
});

test("raw sliders update local classes immediately; manual pins and null Unknown win", () => {
  const attrs = rawAttrs();
  const baseline = initialDraft(attrs, session());
  const draft = { ...baseline, threshold: 0.5, overrides: { 1: "Damaged" } };
  const classes = classifyDraft(attrs, source, draft, baseline);
  assert.deepEqual(classes.classes, ["Damaged", "Damaged", "Unknown"]);
  assert.equal(deriveClass(0.5, 0, 0.5), "NotDamaged");
  assert.equal(deriveClass(0.9, 0.1, 0, 0), "Unknown");
  assert.equal(deriveClass(null, null, 0, 1), "Unknown");
  assert.deepEqual(attrs.classes, ["Damaged", "Damaged", "Unknown"]);
  assert.deepEqual(classifyDraft(attrs, source, { ...baseline, threshold: 1 }, baseline).classes,
    ["NotDamaged", "NotDamaged", "Unknown"]);
});

test("pins equal to current derived classes are not minimized away", () => {
  const baseline = initialDraft(rawAttrs(), session());
  const draft = { ...baseline, overrides: { 0: "Damaged" } };
  assert.equal(isDraftDirty(draft, baseline), true);
  assert.deepEqual(overrideList(draft.overrides), [{ id: 0, class: "Damaged" }]);
  assert.deepEqual(baseline.overrides, {});
});

test("undo manual changes preserves thresholds and inherited saved assignments", () => {
  const baseline = initialDraft(editedAttrs(), session(2));
  const draft = { ...baseline, threshold: 0.7, overrides: { ...baseline.overrides, 1: "Unknown" } };
  assert.equal(countManualChanges(draft, baseline), 1);
  const undone = undoManualChanges(draft, baseline);
  assert.equal(undone.threshold, 0.7);
  assert.deepEqual(undone.overrides, baseline.overrides);
  assert.notEqual(undone.overrides, baseline.overrides);
});

test("retry reuses the exact body and UUID; changed logical payload creates a new attempt", () => {
  let count = 0;
  const uuid = () => `request-${++count}`;
  const draft = initialDraft(rawAttrs(), session());
  const first = saveAttempt(null, ids, source, draft, uuid);
  const retry = saveAttempt(first, ids, source, { ...draft, overrides: {} }, uuid);
  assert.equal(retry, first);
  assert.equal(retry.body, first.body);
  const next = saveAttempt(first, ids, source, { ...draft, overrides: { 2: "Unknown" } }, uuid);
  assert.equal(next.body.clientRequestId, "request-2");
  assert.equal(count, 2);
});

test("review traversal/filtering preserves selected-class semantics and wraps", () => {
  const attrs = rawAttrs(), baseline = initialDraft(attrs, session());
  const classification = classifyDraft(attrs, source, { ...baseline, overrides: { 0: "Unknown" } }, baseline);
  assert.deepEqual(filteredRows(attrs, classification, "Unknown"), [0, 2]);
  assert.deepEqual(filteredRows(attrs, classification, "edited"), [0]);
  assert.equal(nextReviewIndex([0, 2], 2, 1), 0);
  assert.equal(nextReviewIndex([0, 2], 0, -1), 2);
  assert.equal(nextReviewIndex([0, 2, 4], 3, 1), 4);
  assert.equal(nextReviewIndex([0, 2, 4], 3, -1), 2);
  assert.equal(nextReviewIndex([0, 1, 2], -1, 1, (id) => id === 2), 2);
  assert.equal(nextReviewIndex([], -1, 1), null);
});

test("versions default to current generation but keep historical downloads/reports selectable", () => {
  const versions = [
    { version: 9, predictionRevision: "old", gpkgUrl: "old.gpkg" },
    { version: 3, predictionRevision: "current", gpkgUrl: "new.gpkg", predictionAttrsUrl: "new.json" },
  ];
  assert.equal(defaultPredictionVersion(versions, "current"), 3);
  assert.equal(defaultPredictionVersion(versions, "next"), 0);
  assert.equal(predictionSourceOptions(versions, "current").find((item) => item.version === 9).disabled, false);
  assert.equal(predictionSourceOptions(versions, "current", true).find((item) => item.version === 9).disabled, true);
});

test("versioned requests preserve explicit zero, revision and raw report threshold defaults", () => {
  for (const version of [0, 9]) {
    const url = new URL(buildVersionGpkgUrl({ ...ids, version, predictionRevision: "raw generation" }), "https://haste.invalid");
    assert.equal(url.pathname, "/GetModelArtifact");
    assert.equal(url.searchParams.get("version"), String(version));
    assert.equal(url.searchParams.get("predictionRevision"), "raw generation");
    const report = new URL(versionEndpoint("GetAssessmentReport", ids, version), "https://haste.invalid");
    assert.equal(report.searchParams.get("version"), String(version));
    assert.equal(report.searchParams.has("threshold"), false);
  }
  assert.equal(new URL(versionEndpoint("GetAssessmentReport", ids), "https://haste.invalid").searchParams.has("version"), false);
  assert.throws(() => buildVersionGpkgUrl({ ...ids, version: -1 }), /Invalid/);
  assert.throws(() => validateSelectedSource({ version: 2 }, 2), /Invalid/);
  assert.throws(() => validateSelectedSource({ predictionVersion: 0 }, 2), /different prediction version/);
  assert.throws(() => validateVersionManifest([{ version: 1 }, { version: 1 }]), /ambiguous/);
  assert.throws(() => validateVersionManifest({}), /invalid/);
  assert.throws(() => overrideList({ invalid: "Unknown" }), /Invalid explicit/);
});

test("versions change the render identity but not imagery scene identity or camera", () => {
  const before = { ...source, preDisasterImagery: { url: "/pre" }, studyArea: [] };
  const after = { ...before, predictionVersion: 3, predictionAttrsUrl: "/version3" };
  assert.notEqual(predictionRenderKey(before), predictionRenderKey(after));
  assert.equal(visualizerSceneKey(before, "route"), visualizerSceneKey(after, "route"));
  assert.notEqual(visualizerSceneKey(before, "route"), visualizerSceneKey(before, "other-route"));
  assert.equal(visualizerSceneKey(before, "route"), visualizerSceneKey({ ...after, predictedDamageLayer: { url: "/changed-overlay" } }, "route"));
});

for (const code of ["source_changed", "save_conflict", "request_conflict"]) {
  test(`scoped HTTP preserves 409 ${code} without a global helper fallback`, async () => {
    await assert.rejects(requestPredictionJson("/api/PutEditedPredictions", {
      body: { overrides: [] }, fetchResponse: async () => Response.json({ error: { code, message: "Specific conflict" } }, { status: 409 }),
    }), (error) => {
      assert.equal(error.status, 409);
      assert.equal(error.code, code);
      assert.equal(error.message, "Specific conflict");
      assert.ok(predictionErrorMessage(error).includes("draft"));
      return true;
    });
  });
}

test("unknown-version 404 and 500/network errors never become successful raw reports", async () => {
  for (const status of [404, 500]) {
    await assert.rejects(requestPredictionJson("/api/GetAssessmentReport?version=99", {
      fetchResponse: async () => Response.json({ error: "Requested version unavailable" }, { status }),
    }), { status, message: "Requested version unavailable" });
  }
  await assert.rejects(requestPredictionJson("/api/results", { fetchResponse: async () => { throw new TypeError("Network failed"); } }), /Network/);
});

test("confirmed save reloads the RETURNED version and generation, not the prior selection", async () => {
  const events = [];
  const body = buildSavePayload(ids, source, initialDraft(rawAttrs(), session()), "same-id");
  const candidate = { results: { ...source, predictionVersion: 3 }, attrs: { ...editedAttrs(), predictionVersion: 3 } };
  const outcome = await publishPredictionEdit(body, {
    write: async (value) => { events.push(["put", value]); return saved; },
    onSaved: (result) => events.push(["saved", result.version]),
    loadVersion: async (version, revision) => { events.push(["get", version, revision]); return candidate; },
    buildingCount: 3,
  });
  assert.deepEqual(events.map((event) => event[0]), ["put", "saved", "get"]);
  assert.deepEqual(events[2], ["get", 3, source.predictionRevision]);
  assert.equal(outcome.candidate, candidate);
});

test("save success followed by GET failure stays saved and never resubmits the PUT", async () => {
  let puts = 0;
  const outcome = await publishPredictionEdit({ predictionRevision: source.predictionRevision }, {
    write: async () => { puts++; return saved; },
    onSaved: () => {},
    loadVersion: async () => { throw new Error("HTTP 404"); },
  });
  assert.equal(puts, 1);
  assert.equal(outcome.result.version, 3);
  assert.match(outcome.displayError, /Version 3 was saved but could not be displayed/);
  assert.equal(outcome.candidate, undefined);
});

test("rejected and obsolete save responses cannot advertise success or reload a source", async () => {
  let savedCalls = 0, getCalls = 0;
  const options = { onSaved: () => savedCalls++, loadVersion: async () => { getCalls++; } };
  await assert.rejects(publishPredictionEdit({}, { ...options, write: async () => { throw new Error("409"); } }), /409/);
  await assert.rejects(publishPredictionEdit({ predictionRevision: source.predictionRevision }, {
    ...options, write: async () => saved, isCurrent: () => false,
  }), { name: "AbortError" });
  await assert.rejects(publishPredictionEdit({ predictionRevision: source.predictionRevision }, {
    ...options, write: async () => ({ ...saved, predictionAttrsUrl: null }),
  }), /paired artifacts/);
  assert.equal(savedCalls, 0);
  assert.equal(getCalls, 0);
});

test("assessment wording distinguishes saved analyst classes, preserving Unknown exclusion", () => {
  const report = {
    matched: 0,
    predictions: { total: 3, cloudy: 1, knownNonCloudy: 2, predictedDamaged: 1, predictedDamagedPctOfKnown: 50 },
  };
  assert.match(buildAssessmentSummary(report), /model predicted/);
  assert.match(buildAssessmentSummary({ ...report, predictionVersion: 3 }), /saved analyst classes in version 3/);
  assert.match(buildAssessmentSummary({ ...report, predictionVersion: 3 }), /Unknown/);
});
