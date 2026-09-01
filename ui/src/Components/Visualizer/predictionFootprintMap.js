// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Renderer-facing helpers for the predicted-footprint layer.
//
// The results page paints one polygon per predicted building and colours it
// from the browser-side classification (predictionClassify.js) via
// feature-state, so moving the threshold slider recolours instantly with no
// server round-trip. Everything in this module is a plain function over plain
// data — the paint expressions, the class codes they compare against, the
// theme-colour resolution and the duck-typed lookups needed to reach the
// renderer underneath atlas.Map — so it is unit-tested in
// predictionClassify.test.js and the hooks stay pure wiring.
//
// Nothing here imports Azure Maps or touches the DOM at module scope; the two
// browser-only helpers (themeColorLookup, findGlMap) only read what they are
// handed.

import {
  CLASS_DAMAGED,
  CLASS_NOT_DAMAGED,
  CLASS_UNKNOWN,
} from "./predictionClassify.js";

// Tippecanoe writes the buildings layer with `-l buildings`; every feature
// carries the integer `id` (the attribute sidecar's row index) that
// feature-state colouring keys on.
export const PMTILES_SOURCE_LAYER = "buildings";

// Paint expressions compare numbers, so each class gets a code. 0 means "not
// classified yet" — a footprint whose tile arrived before its scores did.
export const CLASS_CODES = {
  [CLASS_DAMAGED]: 1,
  [CLASS_NOT_DAMAGED]: 2,
  [CLASS_UNKNOWN]: 3,
};

/** The paint code for a class, or 0 when it is unknown to us. */
export function classCode(cls) {
  return CLASS_CODES[cls] || 0;
}

// The roles the footprint layer paints. The caller supplies the Fluent token
// for each one (this module deliberately does NOT import
// @fluentui/react-components: it is imported by `node --test`, which cannot
// load the React bundle).
export const COLOR_KEYS = [
  "damaged",
  "notDamaged",
  "unknown",
  "pending",
  "outline",
  "edited",
  "selected",
];

// Last-resort values, used only if a custom property cannot be resolved (the
// renderer needs *some* parseable colour or the layer fails to paint). Named
// CSS colours, deliberately not theme-specific hex codes.
export const FALLBACK_COLORS = {
  damaged: "firebrick",
  notDamaged: "seagreen",
  unknown: "dimgray",
  pending: "lightgray",
  outline: "steelblue",
  edited: "royalblue",
  selected: "white",
};

/**
 * Resolve the map palette.
 *
 * The map's colours come from the active Fluent theme rather than a hardcoded
 * palette: a v9 token is the string "var(--x)", which the renderer cannot
 * parse, so `tokenMap` (role -> token) is unwrapped to its custom property
 * name and handed to `lookup(name)`, which reads it off a live element inside
 * the FluentProvider subtree. Anything the lookup cannot answer falls back to
 * a named CSS colour, so the layer always paints.
 */
export function resolveMapColors(tokenMap, lookup) {
  const colors = {};
  for (const key of COLOR_KEYS) {
    const match = /var\((--[^,)]+)/.exec(String(tokenMap?.[key] ?? ""));
    let resolved = "";
    if (match && typeof lookup === "function") {
      try {
        resolved = String(lookup(match[1]) || "").trim();
      } catch {
        resolved = "";
      }
    }
    colors[key] = resolved || FALLBACK_COLORS[key];
  }
  return colors;
}

/**
 * A lookup backed by an element's computed style — the browser half of
 * resolveMapColors. `element` must live inside the FluentProvider subtree so
 * the theme's custom properties are in scope.
 */
export function themeColorLookup(element) {
  const style =
    element && typeof window !== "undefined" && window.getComputedStyle
      ? window.getComputedStyle(element)
      : null;
  return (name) => (style ? style.getPropertyValue(name) : "");
}

export function fillColorExpression(colors) {
  const paint = colors || FALLBACK_COLORS;
  return [
    "case",
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_DAMAGED]],
    paint.damaged,
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_NOT_DAMAGED]],
    paint.notDamaged,
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_UNKNOWN]],
    paint.unknown,
    paint.pending,
  ];
}

// Buildings filtered out stay on screen as context, but faint.
export const FILL_OPACITY_EXPRESSION = [
  "case",
  ["==", ["feature-state", "dim"], true],
  0.1,
  0.55,
];

export function strokeColorExpression(colors) {
  const paint = colors || FALLBACK_COLORS;
  return [
    "case",
    ["==", ["feature-state", "selected"], true],
    paint.selected,
    ["==", ["feature-state", "edited"], true],
    paint.edited,
    paint.outline,
  ];
}

export const STROKE_WIDTH_EXPRESSION = [
  "case",
  ["==", ["feature-state", "selected"], true],
  4,
  ["==", ["feature-state", "edited"], true],
  2.5,
  1,
];

/**
 * The feature-state one footprint should carry: its class code, whether the
 * current filter dims it, whether the user edited it and whether it is the
 * selected building. Written to every renderer that draws the footprints.
 */
export function footprintFeatureState({
  cls,
  edited = false,
  selected = false,
  dim = false,
} = {}) {
  return {
    cls: classCode(cls),
    dim: !!dim,
    edited: !!edited,
    selected: !!selected,
  };
}

/**
 * atlas.Map has no public setFeatureState; the renderer underneath (a
 * Mapbox-GL fork) does. Same duck-typed scan the Interactive Labeler uses.
 */
export function findGlMap(atlasMap) {
  if (!atlasMap || typeof atlasMap !== "object") return null;
  const direct = [atlasMap.map, atlasMap._map, atlasMap.gl, atlasMap._gl];
  for (const candidate of direct) {
    if (candidate && typeof candidate.setFeatureState === "function") {
      return candidate;
    }
  }
  for (const key of Object.keys(atlasMap)) {
    const value = atlasMap[key];
    if (
      value &&
      typeof value === "object" &&
      typeof value.setFeatureState === "function"
    ) {
      return value;
    }
  }
  return null;
}

/**
 * Azure Maps renames our source/layer inside the renderer's style, so the ids
 * queryRenderedFeatures needs have to be discovered rather than assumed. Used
 * identically for both panes of the swipe map.
 *
 * Only OUR sources are considered: matching every fill layer in the style
 * would include the basemap's own, and then a click anywhere on the map would
 * "hit" a building.
 */
export function discoverFillLayerIds(glMap, fallbackLayerIds, sourceIds) {
  const fallback = Array.isArray(fallbackLayerIds) ? fallbackLayerIds : [];
  const preferredSources = Array.isArray(sourceIds) ? sourceIds : [];
  if (!glMap || typeof glMap.getStyle !== "function") return fallback;
  try {
    const style = glMap.getStyle() || {};
    const ourSources = Object.keys(style.sources || {}).filter(
      (id) => preferredSources.includes(id) || /predict|build/i.test(id)
    );
    const discovered = (style.layers || [])
      .filter(
        (layer) =>
          layer.type === "fill" &&
          (ourSources.includes(layer.source) || fallback.includes(layer.id))
      )
      .map((layer) => layer.id);
    return discovered.length > 0 ? discovered : fallback;
  } catch (error) {
    console.warn("glMap.getStyle() failed:", error);
    return fallback;
  }
}

/**
 * The name the renderer gave our vector source, which is the id every
 * setFeatureState call has to use.
 */
export function discoverVectorSourceId(glMap, preferredId) {
  if (!glMap || typeof glMap.getStyle !== "function") return preferredId;
  try {
    const sources = (glMap.getStyle() || {}).sources || {};
    if (sources[preferredId]) return preferredId;
    const match = Object.keys(sources).find(
      (id) => sources[id]?.type === "vector" && /predict|build/i.test(id)
    );
    return match || preferredId;
  } catch (error) {
    console.warn("glMap.getStyle() failed:", error);
    return preferredId;
  }
}

/**
 * Average of the first ring's vertices — good enough to centre the camera on
 * a building, and far cheaper than a real centroid.
 */
export function featureCentroid(geometry) {
  if (!geometry) return null;
  const ring =
    geometry.type === "Polygon"
      ? geometry.coordinates?.[0]
      : geometry.type === "MultiPolygon"
        ? geometry.coordinates?.[0]?.[0]
        : null;
  if (!Array.isArray(ring) || ring.length === 0) return null;
  let lng = 0;
  let lat = 0;
  for (const position of ring) {
    if (!Array.isArray(position) || position.length < 2) return null;
    lng += position[0];
    lat += position[1];
  }
  return [lng / ring.length, lat / ring.length];
}

/**
 * The pixel rectangle a drag described, normalised so x1/y1 is the top-left
 * corner whichever way the pointer travelled. Returns null for a rectangle
 * too small to be a deliberate box-select (that is a click, not a drag).
 */
export function normalizeSelectionBox(origin, current, minimumSize = 4) {
  if (!origin || !current) return null;
  const x1 = Math.min(origin.x, current.x);
  const y1 = Math.min(origin.y, current.y);
  const x2 = Math.max(origin.x, current.x);
  const y2 = Math.max(origin.y, current.y);
  if (x2 - x1 < minimumSize || y2 - y1 < minimumSize) return null;
  return { x1, y1, x2, y2 };
}
