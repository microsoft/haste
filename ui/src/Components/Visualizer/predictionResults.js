// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Pure decision logic for the results view's prediction layer.
//
// The results page (Visualizer) draws one model's predicted building
// footprints as vectors and, in edit mode, lets an analyst reclassify them.
// Both HASTE workflows land here:
//
//   • inference models ship pre-coloured rasters (`_visualizer.tif` and
//     `_predictions.tif`) *plus* per-building predictions, and
//   • embedding models ship no raster at all — the vector footprints are the
//     only thing there is to draw.
//
// So every "is this layer actually there?" question has to be answered from
// the payload rather than assumed, which is what this module does. Nothing
// here touches React, the DOM, Azure Maps or fetch, so the rules are
// unit-tested in predictionClassify.test.js.
//
// GetVisualizerResults is being made vector-first in parallel with this UI:
// it gains `footprintTilesUrl`, `predictionAttrsUrl`, `predictionsReady`,
// `flavor` and `supportsThreshold`, and returns null rasters for embedding
// models. Every reader below treats those fields as OPTIONAL and falls back
// to what today's payload can tell us, so the page works against either
// version of the API.

// ── Raster availability ─────────────────────────────────────────────────────

// GetVisualizerResults builds its TiTiler template by string interpolation,
// so a model with no COG still yields a syntactically fine tile URL whose
// `url=` parameter is empty. Requesting those tiles can only ever fail, so an
// empty `url=` means "this raster does not exist" exactly like a null layer.
const EMPTY_TITILER_URL = /[?&]url=(?:&|$)/;

/** True when a layer block from GetVisualizerResults can actually be drawn. */
export function hasRasterLayer(layer) {
  const url = typeof layer?.url === "string" ? layer.url.trim() : "";
  if (url === "") return false;
  return !EMPTY_TITILER_URL.test(url);
}

/**
 * Which raster overlays this model has, keyed by the customId the map layers
 * are registered under. The InfoPanel checkboxes are driven from this so an
 * embedding model never offers a toggle for a layer that was never added.
 */
export function rasterLayerAvailability(results) {
  return {
    predictedDamageLayer: hasRasterLayer(results?.predictedDamageLayer),
    predictionsLayer: hasRasterLayer(results?.predictionsLayer),
  };
}

/** True when the model has no raster overlays at all (the embedding case). */
export function hasAnyRasterLayer(results) {
  const available = rasterLayerAvailability(results);
  return available.predictedDamageLayer || available.predictionsLayer;
}

// ── Artifact endpoints ──────────────────────────────────────────────────────

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * A version query value, or null when there is nothing to pin.
 *
 * `0` is a real answer — GetModelArtifact reads it as "the raw model output,
 * explicitly" — so it survives, while null/undefined/"" mean "say nothing and
 * let the route apply its own default".
 */
export function normalizeVersionParam(value) {
  if (value === null || value === undefined || value === "") return null;
  const version = Number(value);
  if (!Number.isFinite(version) || version < 0) return null;
  return Math.floor(version);
}

/**
 * The API-relative GetModelArtifact endpoint for one artifact `kind`.
 *
 * `imageLayerId` is optional in the contract (the route falls back to the
 * model's own layer) but is always sent when known: footprint tiles are
 * layer-scoped, and being explicit costs nothing.
 *
 * `version` is optional and only meaningful for the per-version kinds
 * (`prediction_attrs`, `gpkg`): omitted serves the model-level artifact (the
 * raw output), `0` forces the raw output explicitly, and `N` serves that
 * edited version's own artifact.
 */
export function buildArtifactUrl({
  projectId,
  imageLayerId,
  modelId,
  kind,
  version,
} = {}) {
  const params = new URLSearchParams();
  params.set("projectId", String(projectId ?? ""));
  if (cleanString(imageLayerId)) {
    params.set("imageLayerId", String(imageLayerId));
  }
  params.set("modelId", String(modelId ?? ""));
  params.set("kind", String(kind ?? ""));
  const pinned = normalizeVersionParam(version);
  if (pinned !== null) params.set("version", String(pinned));
  return `GetModelArtifact?${params.toString()}`;
}

/**
 * Where to fetch the footprint PMTiles archive and the score sidecar.
 *
 * Prefers whatever the server handed back so the API stays free to move the
 * artifacts, and reconstructs the standard endpoints when those fields are
 * missing (the pre-vector-first payload).
 *
 * The sidecar is PER VERSION and the geometry is not: every version of a
 * model describes the same buildings, so the PMTiles archive is shared while
 * the scores and classes come from the selected version's own file. When the
 * payload was served for version N and did not name a sidecar, the
 * reconstructed endpoint is pinned to N — the raw model's sidecar is never
 * substituted, because it describes the model's classes and not the
 * analyst's.
 */
export function resolvePredictionArtifacts(results, ids = {}) {
  const version = resolveActiveVersion(results);
  const footprintTilesUrl =
    cleanString(results?.footprintTilesUrl) ||
    buildArtifactUrl({ ...ids, kind: "footprint_pmtiles" });
  const predictionAttrsUrl =
    cleanString(results?.predictionAttrsUrl) ||
    buildArtifactUrl({ ...ids, kind: "prediction_attrs", version });
  return { footprintTilesUrl, predictionAttrsUrl, version };
}

// ── Model shape ─────────────────────────────────────────────────────────────

export const FLAVOR_INFERENCE = "inference";
export const FLAVOR_EMBEDDING = "embedding";

/**
 * Which workflow produced these predictions. The edit session is the
 * authority (it reads the GeoPackage); the results payload is used when no
 * session has been fetched yet, and "" means "not known yet".
 */
export function resolveModelFlavor({ results, session } = {}) {
  const fromSession = cleanString(session?.flavor);
  if (fromSession) return fromSession;
  return cleanString(results?.flavor);
}

/**
 * Whether re-thresholding this model's scores means anything.
 *
 * The embedding producer writes `damage_pct_0m` as a degenerate 0/1 copy of
 * the predicted class, so a slider over it would just move buildings between
 * "all damaged" and "none damaged". When nothing says otherwise we assume the
 * slider IS meaningful: hiding it on an inference model silently removes the
 * feature, while showing it on an embedding model is merely useless.
 */
export function resolveSupportsThreshold({ results, session } = {}) {
  if (typeof session?.supportsThreshold === "boolean") {
    return session.supportsThreshold;
  }
  if (typeof results?.supportsThreshold === "boolean") {
    return results.supportsThreshold;
  }
  return resolveModelFlavor({ results, session }) !== FLAVOR_EMBEDDING;
}

/**
 * Are the vector artifacts built? `null` when nothing has said either way.
 *
 * The session's per-artifact flags win when present because they are what the
 * preparation poll refreshes; the results payload only reports readiness as
 * it was when the page loaded.
 */
export function resolvePredictionsReady({ results, session } = {}) {
  if (
    typeof session?.tilesReady === "boolean" &&
    typeof session?.attrsReady === "boolean"
  ) {
    return session.tilesReady && session.attrsReady;
  }
  if (typeof results?.predictionsReady === "boolean") {
    return results.predictionsReady;
  }
  return null;
}

/**
 * How many buildings this model predicted, when the payload already says.
 * Zero is a real answer — it is what makes the difference between "still
 * preparing" and "there is nothing to prepare" — so it must survive.
 */
export function resolveInitialBuildingCount(results) {
  const raw = results?.buildingCount;
  if (raw === null || raw === undefined || raw === "") return null;
  const count = Number(raw);
  return Number.isFinite(count) && count >= 0 ? count : null;
}

/**
 * Saved edited-prediction versions the results payload already carries, so
 * the version history is populated before any edit session is fetched.
 */
export function resolveInitialVersions(results) {
  return Array.isArray(results?.predictionVersions)
    ? results.predictionVersions
    : [];
}

/**
 * The server's own explanation for a layer that is not ready — "not
 * processed", "still preparing", and so on. Preferred over our generic copy
 * because it knows which workflow the model came from.
 */
export function resolveReadinessDetail(results) {
  return cleanString(results?.predictionsReadiness?.detail);
}

// Why the server says the vector artifacts are not ready. `preparing` is the
// only one a tiling job can fix; the rest need the user to go and do
// something else entirely, so they must not be dressed up as "nearly there".
export const READINESS_READY = "ready";
export const READINESS_PREPARING = "preparing";
export const READINESS_NOT_PROCESSED = "not_processed";
export const READINESS_NO_PREDICTIONS = "no_predictions";
export const READINESS_NO_BUILDINGS = "no_buildings";

export function resolveReadinessReason(results) {
  return cleanString(results?.predictionsReadiness?.reason);
}

/**
 * Whether it is worth queueing a tile-preparation job.
 *
 * Only when the server has not ruled it out. An unrecognised or absent
 * reason still queues — that is the pre-contract behaviour and the job is
 * harmless — but a model that was never processed, has no predictions, or
 * has no buildings can never produce artifacts, so asking would just spin.
 */
export function shouldRequestPreparation(reason) {
  switch (cleanString(reason)) {
    case READINESS_NOT_PROCESSED:
    case READINESS_NO_PREDICTIONS:
    case READINESS_NO_BUILDINGS:
      return false;
    default:
      return true;
  }
}

/**
 * The footprint status a server-declared reason implies, or null when it
 * implies nothing on its own. Defined with the statuses it returns, below.
 */

// ── Edited versions ─────────────────────────────────────────────────────────

/**
 * Which edited version the payload was served from, or null for the model's
 * raw output. Zero is the raw output too — `GetVisualizerResults?version=0`
 * forces it — so it normalises to null rather than surviving as a falsy
 * number that reads like a real version.
 */
export function resolveActiveVersion(results) {
  const raw = results?.predictionVersion;
  if (raw === null || raw === undefined || raw === "") return null;
  const version = Number(raw);
  if (!Number.isFinite(version) || version <= 0) return null;
  return version;
}

/** One line naming what the map is currently showing. */
export function describeServedVersion(activeVersion) {
  return activeVersion
    ? `Showing edited version ${activeVersion}.`
    : "Showing the model's own predictions.";
}

/**
 * Whether the version the payload was served from is the newest saved state
 * of this model's predictions.
 *
 * SERVER-DECIDED, never recomputed here: the API knows about versions this
 * page may not have listed yet, and it is the same flag the report routes
 * resolve their default from. Absent (an older payload) means "assume
 * newest", which is what omitting `version` has always meant.
 */
export function resolveVersionIsLatest(results) {
  return results?.predictionVersionIsLatest !== false;
}

/**
 * True when the payload was served for an edited version whose sidecar has
 * not been built yet.
 *
 * That version genuinely has nothing to draw — the raw sidecar is never
 * substituted — so the page shows the "still preparing" state instead of an
 * empty map. Requires the server to actually say so (`attrsReady: false` or
 * `predictionsReady: false`): a payload that simply omits the URL falls
 * through to the reconstructed version-pinned endpoint, which 404s on its own
 * if the file really is missing.
 */
export function versionSidecarPending(results) {
  if (resolveActiveVersion(results) === null) return false;
  if (cleanString(results?.predictionAttrsUrl)) return false;
  if (results?.predictionsReadiness?.attrsReady === false) return true;
  return results?.predictionsReady === false;
}

// ── Footprint layer status ──────────────────────────────────────────────────

// LOADING      artifacts are being fetched (or we do not know yet).
// PREPARING    the tiling job has not produced them yet; we poll.
// READY        footprints are on the map.
// EMPTY        this model predicted no buildings at all.
// UNAVAILABLE  something failed, or there is nothing to fetch.
export const FOOTPRINTS_LOADING = "loading";
export const FOOTPRINTS_PREPARING = "preparing";
export const FOOTPRINTS_READY = "ready";
export const FOOTPRINTS_EMPTY = "empty";
export const FOOTPRINTS_UNAVAILABLE = "unavailable";

/**
 * The footprint status a server-declared readiness reason implies, or null
 * when it implies nothing on its own. `ready` is deliberately null: the
 * payload was written before the browser tried to download anything, so it
 * cannot say whether the layer is actually on the map yet.
 */
export function statusForReadinessReason(reason) {
  switch (cleanString(reason)) {
    case READINESS_NO_BUILDINGS:
      return FOOTPRINTS_EMPTY;
    case READINESS_NOT_PROCESSED:
    case READINESS_NO_PREDICTIONS:
      return FOOTPRINTS_UNAVAILABLE;
    case READINESS_PREPARING:
      return FOOTPRINTS_PREPARING;
    default:
      return null;
  }
}

/**
 * What the results page should show for the footprint layer, given what it
 * has learned so far. Ordering is deliberate:
 *
 *   1. a model with zero predicted buildings is EMPTY whatever else is true —
 *      no job will ever produce footprints for it;
 *   2. a hard failure is UNAVAILABLE, so the user gets the reason instead of
 *      an empty map;
 *   3. footprints actually on the map are READY even if a stale payload
 *      still says otherwise;
 *   4. the server's own reason then decides — it distinguishes "preparing"
 *      (a job will fix it) from "never processed" (nothing will);
 *   5. artifacts known to be missing mean PREPARING (with or without a job
 *      already queued), never "ready but blank".
 */
export function resolveFootprintStatus({
  loaded = false,
  loading = false,
  error = "",
  ready = null,
  buildingCount = null,
  reason = "",
} = {}) {
  if (typeof buildingCount === "number" && buildingCount === 0) {
    return FOOTPRINTS_EMPTY;
  }
  if (cleanString(error)) return FOOTPRINTS_UNAVAILABLE;
  if (loaded) return FOOTPRINTS_READY;
  const declared = statusForReadinessReason(reason);
  if (declared) return declared;
  if (ready === false) return FOOTPRINTS_PREPARING;
  if (loading) return FOOTPRINTS_LOADING;
  return FOOTPRINTS_LOADING;
}

/** Only a fully loaded vector layer can be edited. */
export function canEditFootprints(status) {
  return status === FOOTPRINTS_READY;
}

/**
 * Copy for the status note the results page shows instead of leaving the map
 * silently empty. Returns null when there is nothing to say (READY).
 *
 * `intent` maps onto the Fluent MessageBar intents.
 */
export function describeFootprintStatus(status, context = {}) {
  const detail = cleanString(context.detail);
  switch (status) {
    case FOOTPRINTS_LOADING:
      return {
        intent: "info",
        title: "Loading predicted buildings",
        body:
          detail ||
          "Streaming building footprints and per-building prediction scores.",
      };
    case FOOTPRINTS_PREPARING:
      return {
        intent: "info",
        title: "Predicted buildings are still being prepared",
        body:
          detail ||
          "The editable footprint tiles and prediction scores are being " +
            "generated. They appear here on their own — no need to reload.",
      };
    case FOOTPRINTS_EMPTY:
      return {
        intent: "warning",
        title: "No predicted buildings",
        body:
          detail ||
          "This model has no per-building predictions. Run inference, or " +
            "predict all buildings in the Interactive Labeler, and come back.",
      };
    case FOOTPRINTS_UNAVAILABLE:
      return {
        intent: "error",
        title: "Predicted buildings unavailable",
        body: detail || "The building footprints could not be loaded.",
      };
    default:
      return null;
  }
}

/** Tooltip for the edit affordance, explaining any disabled state. */
export function describeEditAvailability(status) {
  if (canEditFootprints(status)) {
    return "Edit these predictions and save them as a new version";
  }
  if (status === FOOTPRINTS_EMPTY) {
    return "This model has no per-building predictions to edit";
  }
  if (status === FOOTPRINTS_PREPARING) {
    return "Editing opens once the predicted buildings finish preparing";
  }
  if (status === FOOTPRINTS_UNAVAILABLE) {
    return "The predicted buildings could not be loaded, so they cannot be edited";
  }
  return "Loading predicted buildings…";
}

// ── Layer list ──────────────────────────────────────────────────────────────

/**
 * The layer toggles the results page should offer, in draw order.
 *
 * A checkbox for a layer that was never added to the map is worse than no
 * checkbox at all, so the rasters are listed only when this model actually has
 * them — for an embedding model that leaves just the footprints. The footprint
 * row is always listed (it is the whole point of the page) but is disabled
 * until the vectors are on the map, which doubles as a hint that something is
 * still coming.
 */
export function visualizerLayerOptions({ results, footprintStatus } = {}) {
  const rasters = rasterLayerAvailability(results);
  const options = [];
  if (rasters.predictedDamageLayer) {
    options.push({
      key: "predictedDamageLayer",
      label: "Predicted building damage",
      disabled: false,
    });
  }
  if (rasters.predictionsLayer) {
    options.push({
      key: "predictionsLayer",
      label: "Raw model output",
      disabled: false,
    });
  }
  options.push({
    key: "footprints",
    label: "Predicted building footprints",
    disabled: footprintStatus !== FOOTPRINTS_READY,
  });
  return options;
}

// ── Unsaved work ────────────────────────────────────────────────────────────

const EPSILON = 1e-9;

function sameNumber(a, b) {
  const left = typeof a === "number" && Number.isFinite(a) ? a : 0;
  const right = typeof b === "number" && Number.isFinite(b) ? b : 0;
  return Math.abs(left - right) < EPSILON;
}

/** True when two override maps hold exactly the same per-building classes. */
export function sameOverrides(left, right) {
  const a = left || {};
  const b = right || {};
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((key) => a[key] === b[key]);
}

/**
 * True when leaving edit mode would throw work away: overrides that differ
 * from the last saved set, or thresholds moved away from the baseline that
 * save established.
 *
 * Saving updates the baseline (thresholds AND overrides), so edits that were
 * just written to a new version stop counting as unsaved — otherwise the page
 * would warn about discarding work it had already stored.
 */
export function hasUnsavedEdits({
  overrides,
  threshold,
  unknownThreshold,
  baseline,
} = {}) {
  if (!baseline) return !!overrides && Object.keys(overrides).length > 0;
  if (!sameOverrides(overrides, baseline.overrides)) return true;
  return (
    !sameNumber(threshold, baseline.threshold) ||
    !sameNumber(unknownThreshold, baseline.unknownThreshold)
  );
}

/** How many overrides differ from the last saved set. */
export function countUnsavedOverrides(overrides, baseline) {
  const current = overrides || {};
  const saved = baseline?.overrides || {};
  let count = 0;
  for (const key of Object.keys(current)) {
    if (current[key] !== saved[key]) count++;
  }
  for (const key of Object.keys(saved)) {
    if (!(key in current)) count++;
  }
  return count;
}

/** Confirmation copy for discarding unsaved edits. */
export function describeUnsavedEdits(overrides, baseline) {
  const count = countUnsavedOverrides(overrides, baseline);
  if (count === 0) {
    return (
      "The threshold changes you made have not been saved. " +
      "Leaving edit mode discards them."
    );
  }
  return (
    `${count.toLocaleString()} ${count === 1 ? "building" : "buildings"} ` +
    "changed by hand have not been saved. Leaving edit mode discards them."
  );
}
