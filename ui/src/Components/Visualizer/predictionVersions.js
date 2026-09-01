// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Pure decision logic for CHOOSING which prediction version the results map
// draws, and for downloading any of them.
//
// A model's predictions are append-only: the raw model output plus every
// version an analyst saved from edit mode. GetVisualizerResults serves one of
// them at a time — omit `version` for the newest saved state, pass `0` for
// the raw output, pass `N` for that version — and returns a version-pinned
// `predictionAttrsUrl` plus `predictionVersionIsLatest`. So "which versions
// can I pick, which one is on the map, which one can't be drawn yet, and what
// do I have to disclose about the reports?" is a set of plain functions over
// the payload, which is what this module holds. Nothing here touches React,
// Azure Maps or fetch; the rules are unit-tested in predictionClassify.test.js.
//
// Two things this module deliberately does NOT do:
//
//   • it never recomputes "is this the newest version?" from the version
//     list — the server says so, and it knows about versions this page may
//     not have listed yet; and
//   • it never points a version at another version's artifacts. A version
//     with no sidecar yet is offered as DISABLED with the reason, rather than
//     silently drawing the raw model's classes under an edited version's name.
import { latestVersion, sortVersionsDescending } from "./predictionClassify.js";
import { buildArtifactUrl, normalizeVersionParam } from "./predictionResults.js";

/** The raw model output, as a selection value. */
export const RAW_VERSION = 0;
export const RAW_VERSION_LABEL = "Raw model output";

/** Why a saved version cannot be selected yet. */
export const VERSION_PREPARING_REASON =
  "This version's per-building scores are still being generated, so it " +
  "cannot be drawn yet. It becomes selectable on its own once the backfill " +
  "finishes.";

// How often to re-ask GetVisualizerResults for a version whose sidecar is
// still being backfilled. Same 5s rhythm as the tile-preparation poll (see
// predictionPrep.js) so the app has one polling cadence, not several.
export const VERSION_POLL_INTERVAL_MS = 5000;

// Give up after 60 polls (5 minutes). Backfilling one already-saved version's
// sidecar is a small job compared with tiling a whole layer, and the analyst
// can always pick another version in the meantime, so this stops far sooner
// than the tiling wait.
export const MAX_VERSION_POLL_ATTEMPTS = 60;

/** A selection value normalised to an integer >= 0 (raw output = 0). */
export function normalizeVersionSelection(value) {
  const version = normalizeVersionParam(value);
  return version === null ? RAW_VERSION : version;
}

/** The dropdown key for a selection. Fluent's Dropdown works in strings. */
export function versionKey(version) {
  return String(normalizeVersionSelection(version));
}

/** Human name for one version. */
export function versionLabel(version) {
  const normalized = normalizeVersionSelection(version);
  return normalized === RAW_VERSION
    ? RAW_VERSION_LABEL
    : `Version ${normalized}`;
}

/** The same name inside a sentence ("the map is showing …"). */
export function describeVersionInline(version) {
  const normalized = normalizeVersionSelection(version);
  return normalized === RAW_VERSION
    ? "the model's own predictions"
    : `edited version ${normalized}`;
}

/** True when a saved version's own sidecar exists and can be drawn. */
export function isVersionReady(entry) {
  const url = entry?.predictionAttrsUrl;
  return typeof url === "string" && url.trim() !== "";
}

/**
 * The GetVisualizerResults endpoint for one version selection.
 *
 * `version` is left out entirely when it is null/undefined, which is how the
 * page asks for the server's own default (the newest saved state); `0` asks
 * for the raw model output explicitly.
 */
export function buildVisualizerResultsUrl({
  projectId,
  imageLayerId,
  modelId,
  version,
} = {}) {
  const params = new URLSearchParams();
  params.set("projectId", String(projectId ?? ""));
  params.set("imageLayerId", String(imageLayerId ?? ""));
  params.set("modelId", String(modelId ?? ""));
  const pinned = normalizeVersionParam(version);
  if (pinned !== null) params.set("version", String(pinned));
  return `GetVisualizerResults?${params.toString()}`;
}

/**
 * Where to download one version's GeoPackage.
 *
 * Always the GetModelArtifact route, never the blob SAS URL the model rows
 * rewrite: the artifact route already carries auth, managed identity and
 * Range, and is what every other artifact on this page goes through.
 */
export function buildVersionGpkgUrl({
  projectId,
  imageLayerId,
  modelId,
  version,
} = {}) {
  return buildArtifactUrl({
    projectId,
    imageLayerId,
    modelId,
    kind: "gpkg",
    version: normalizeVersionSelection(version),
  });
}

/** Tooltip/aria copy for a download action. */
export function describeVersionDownload(version) {
  const normalized = normalizeVersionSelection(version);
  return normalized === RAW_VERSION
    ? "Download the model's own predictions as a GeoPackage (.gpkg)"
    : `Download version ${normalized} as a GeoPackage (.gpkg)`;
}

/**
 * The options the version selector offers: every saved version newest first,
 * then the raw model output.
 *
 * Raw goes last on purpose — the newest edit is what an analyst normally
 * wants, and the raw output is the fallback they drop to deliberately.
 *
 * Each option carries everything the control needs to render honestly:
 * whether it is the newest saved state, whether it is the one currently on
 * the map, and whether it can be picked at all (a version whose sidecar has
 * not been backfilled yet cannot).
 */
export function versionSelectorOptions({
  versions = [],
  servedVersion = null,
} = {}) {
  const served = normalizeVersionSelection(servedVersion);
  const ordered = sortVersionsDescending(versions).filter(
    (entry) => normalizeVersionParam(entry?.version) > 0
  );
  const newest = latestVersion(ordered);
  const newestNumber = newest ? normalizeVersionParam(newest.version) : null;

  const options = ordered.map((entry) => {
    const version = normalizeVersionParam(entry.version);
    const ready = isVersionReady(entry);
    const isNewest = version === newestNumber;
    const isServed = version === served;
    const markers = [];
    if (isNewest) markers.push("newest");
    if (isServed) markers.push("on the map");
    if (!ready) markers.push("preparing…");
    return {
      key: versionKey(version),
      version,
      label: versionLabel(version),
      text: markers.length
        ? `${versionLabel(version)} · ${markers.join(" · ")}`
        : versionLabel(version),
      disabled: !ready,
      disabledReason: ready ? "" : VERSION_PREPARING_REASON,
      isNewest,
      isServed,
      isRaw: false,
    };
  });

  const rawServed = served === RAW_VERSION;
  options.push({
    key: versionKey(RAW_VERSION),
    version: RAW_VERSION,
    label: RAW_VERSION_LABEL,
    text: rawServed ? `${RAW_VERSION_LABEL} · on the map` : RAW_VERSION_LABEL,
    disabled: false,
    disabledReason: "",
    // The raw output is only "newest" when nothing has ever been saved.
    isNewest: newestNumber === null,
    isServed: rawServed,
    isRaw: true,
  });

  return options;
}

/** The option matching a selection, or null. */
export function findVersionOption(options, version) {
  const key = versionKey(version);
  return (options || []).find((option) => option.key === key) || null;
}

/** What the closed dropdown displays for the current selection. */
export function selectedVersionText(options, version) {
  const option = findVersionOption(options, version);
  return option ? option.text : versionLabel(version);
}

/**
 * The disclosure that the map and the reports are looking at different
 * versions, or null when they agree.
 *
 * Version selection moves the MAP only: Assessment and Validation always read
 * the newest saved version. Saying so where the analyst can see it is the
 * difference between a disclosed limitation and a wrong number nobody
 * questioned. `isLatest` comes straight from `predictionVersionIsLatest`.
 */
export function describeReportDivergence({
  isLatest = true,
  servedVersion = null,
  versions = [],
} = {}) {
  if (isLatest) return null;
  const newest = latestVersion(versions);
  const newestNumber = newest ? normalizeVersionParam(newest.version) : null;
  const newestName =
    newestNumber && newestNumber > 0 ? `version ${newestNumber}` : "the newest";
  return {
    title: "Reports use the newest version",
    body:
      `The map is showing ${describeVersionInline(servedVersion)}. The ` +
      `Assessment and Validation reports always read the newest saved ` +
      `version (${newestName}), so their numbers will not match what is on ` +
      `screen.`,
  };
}

/** Copy for a selected version whose sidecar is still being backfilled. */
export function describeVersionSidecarPending({
  version = null,
  versionsPending = null,
} = {}) {
  const normalized = normalizeVersionSelection(version);
  const pending = Number(versionsPending);
  const queue =
    Number.isFinite(pending) && pending > 0
      ? ` ${pending.toLocaleString()} saved ${
          pending === 1 ? "version is" : "versions are"
        } waiting to be rebuilt.`
      : "";
  return {
    title: `${versionLabel(normalized)} is still being prepared`,
    body:
      `This version was saved before its per-building scores were ` +
      `generated, so there is nothing to draw for it yet. HASTE has asked ` +
      `for them; the map fills in on its own when they arrive.${queue} ` +
      `Pick another version — ${RAW_VERSION_LABEL.toLowerCase()} always ` +
      `works — to keep working in the meantime.`,
  };
}

/** Copy for a version switch that failed, naming what is still on screen. */
export function describeVersionSwitchFailure({
  version = null,
  shownVersion = null,
  message = "",
} = {}) {
  const detail = typeof message === "string" ? message.trim() : "";
  return {
    title: `${versionLabel(version)} could not be loaded`,
    body:
      `${detail ? `${detail} ` : ""}The map still shows ` +
      `${describeVersionInline(shownVersion)}.`,
  };
}

/**
 * Why the class thresholds are inert on an edited version.
 *
 * A saved version stores the class an analyst decided per building, and the
 * server keeps the model's raw fractions untouched beside them. Re-deriving
 * classes from those fractions would throw the analyst's decision away, so
 * the sliders are hidden and this says why rather than leaving a control
 * silently missing.
 */
export function describeSavedClassNote(version) {
  const normalized = normalizeVersionSelection(version);
  if (normalized === RAW_VERSION) return "";
  return (
    `Version ${normalized} stores the class each building was saved with, ` +
    `so the thresholds no longer apply to it. Switch to ` +
    `${RAW_VERSION_LABEL.toLowerCase()} to work from the model's scores again.`
  );
}

/** Confirmation copy for switching versions with unsaved edits pending. */
export function describeVersionSwitchDiscard(version) {
  return (
    `Switching to ${versionLabel(version).toLowerCase()} reloads the ` +
    `predictions from the server, which discards the edits you have not ` +
    `saved. Save them as a new version first if you want to keep them.`
  );
}

/**
 * Whether to schedule another "has this version's sidecar appeared yet?"
 * poll. Only while a version really is pending, and only up to the cap so a
 * forgotten tab cannot poll forever.
 */
export function shouldPollVersionSidecar({
  pending = false,
  attempt = 0,
  maxAttempts = MAX_VERSION_POLL_ATTEMPTS,
} = {}) {
  if (!pending) return false;
  const current = Number.isFinite(Number(attempt)) ? Number(attempt) : 0;
  return current < maxAttempts;
}

// ── Choosing which predictions to READ (download / report) ──────────────────
//
// Separate from versionSelectorOptions on purpose. That one is for the MAP,
// so it disables any version whose attribute sidecar has not been backfilled
// — without the sidecar there are no per-building classes to colour with.
// Downloads and reports read the GeoPackage itself, where a missing sidecar
// is irrelevant, so gating on it there would hide a perfectly good file.

/**
 * The prediction sources a model can be downloaded from or reported on:
 * every saved version that has a GeoPackage, newest first, raw output last.
 *
 * Always returns at least the raw option, so callers can render the control
 * unconditionally and use the length to decide whether a choice exists.
 */
export function predictionSourceOptions(versions = []) {
  const ordered = sortVersionsDescending(versions).filter(
    (entry) => normalizeVersionParam(entry?.version) > 0 && entry?.gpkgUrl
  );
  const newest = latestVersion(ordered);
  const newestNumber = newest ? normalizeVersionParam(newest.version) : null;

  const options = ordered.map((entry) => {
    const version = normalizeVersionParam(entry.version);
    const isNewest = version === newestNumber;
    return {
      key: versionKey(version),
      version,
      label: versionLabel(version),
      text: isNewest
        ? `${versionLabel(version)} · newest`
        : versionLabel(version),
      isNewest,
      isRaw: false,
    };
  });

  options.push({
    key: versionKey(RAW_VERSION),
    version: RAW_VERSION,
    label: RAW_VERSION_LABEL,
    text: RAW_VERSION_LABEL,
    // Raw is only the newest state when nothing has ever been saved.
    isNewest: newestNumber === null,
    isRaw: true,
  });

  return options;
}

/**
 * What a download or report should read unless the analyst says otherwise:
 * the newest saved edit, else the raw output.
 *
 * Matches the server's own rule (`describe_prediction_source` with no
 * version), so the default the UI shows is the one the API would have picked
 * on its own.
 */
export function defaultPredictionVersion(versions = []) {
  const newest = predictionSourceOptions(versions).find(
    (option) => option.isNewest
  );
  return newest ? newest.version : RAW_VERSION;
}

/** Whether there is more than one source to choose between. */
export function hasPredictionVersionChoice(versions = []) {
  return predictionSourceOptions(versions).length > 1;
}
