// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Renderer helpers adapted from PR136. No React, SDK import or DOM at module scope.
import { CLASS_DAMAGED, CLASS_NOT_DAMAGED, CLASS_UNKNOWN, indexById } from "./predictionClassify.js";
import { isOptionalAzureBasemapAuthError } from "../../util/azureMapsErrors.js";

export const PMTILES_SOURCE_LAYER = "buildings";
export const CLASS_CODES = { [CLASS_DAMAGED]: 1, [CLASS_NOT_DAMAGED]: 2, [CLASS_UNKNOWN]: 3 };
export const FALLBACK_COLORS = {
  damaged: "firebrick", notDamaged: "seagreen", unknown: "dimgray",
  pending: "lightgray", outline: "steelblue",
  edited: "royalblue", selected: "white",
};

export function resolveMapColors(tokenMap, lookup) {
  return Object.fromEntries(Object.keys(FALLBACK_COLORS).map((key) => {
    const name = /var\((--[^,)]+)/.exec(tokenMap[key] || "")?.[1];
    return [key, (name && lookup(name)?.trim()) || FALLBACK_COLORS[key]];
  }));
}

export function fillColorExpression(colors = FALLBACK_COLORS) {
  return [
    "case",
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_DAMAGED]], colors.damaged,
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_NOT_DAMAGED]], colors.notDamaged,
    ["==", ["feature-state", "cls"], CLASS_CODES[CLASS_UNKNOWN]], colors.unknown,
    colors.pending,
  ];
}
export function strokeColorExpression(colors) {
  return ["case", ["boolean", ["feature-state", "selected"], false], colors.selected,
    ["boolean", ["feature-state", "edited"], false], colors.edited, colors.outline];
}
export function featureCentroid(geometry) {
  const ring = geometry?.type === "Polygon" ? geometry.coordinates?.[0] :
    geometry?.type === "MultiPolygon" ? geometry.coordinates?.[0]?.[0] : null;
  if (!ring?.length) return null;
  return ring.reduce((sum, point) => [sum[0] + point[0] / ring.length, sum[1] + point[1] / ring.length], [0, 0]);
}

export function findGlMap(atlasMap) {
  if (!atlasMap) return null;
  return [atlasMap.map, atlasMap._map, atlasMap.gl, atlasMap._gl, ...Object.values(atlasMap)]
    .find((value) => value && typeof value.setFeatureState === "function") || null;
}

/**
 * Atlas can rename the source. Discover ONLY the vector source this operation
 * added, never a /build/ regex that could capture the basemap's buildings.
 */
export function discoverVectorSourceId(gl, previousSources, preferredId, sourceUrl) {
  const sources = gl.getStyle()?.sources || {};
  const added = Object.keys(sources).filter(
    (id) => !previousSources.has(id) && sources[id].type === "vector" &&
      (id === preferredId || id.endsWith(`-${preferredId}`) ||
        id.endsWith(`_${preferredId}`) || (sourceUrl && sources[id].url === sourceUrl)),
  );
  if (added.length > 1) throw new Error("Prediction renderer created ambiguous vector sources.");
  return added[0] || null;
}

export function discoverFillLayerIds(gl, sourceId) {
  return (gl.getStyle()?.layers || []).filter(
    (layer) => layer.type === "fill" && layer.source === sourceId &&
      layer["source-layer"] === PMTILES_SOURCE_LAYER,
  ).map((layer) => layer.id);
}

const PANE_IDS = ["Primary", "Secondary"];
const RENDERER_TIMEOUT_MS = 30000;

/**
 * PR136's two-pane renderer, without editor state/handlers. A controller keeps
 * the imperative SDK out of React and makes the actual two-renderer lifecycle
 * testable. Ready means BOTH renderer sources/layers exist and have loaded.
 */
export function createPredictionRenderer({ atlas, maps, archiveKey, attrs, onError }) {
  if (maps.length !== 2 || maps.some((map) => !map)) {
    throw new Error("Prediction footprints require both swipe maps.");
  }
  const byId = indexById(attrs);
  const panes = [];
  const locations = new Map();
  const disposers = new Set();
  let presentation = null;
  let disposed = false;
  let ready = false;
  let frame = null;
  let timer;
  let resolveReady;
  let rejectReady;
  const readyPromise = new Promise((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  // Consumers attach their handlers after construction, which may fail early.
  readyPromise.catch(() => {});

  function dispose() {
    if (disposed) return;
    disposed = true;
    clearTimeout(timer);
    if (frame !== null) cancelAnimationFrame(frame);
    for (const cleanup of disposers) cleanup();
    disposers.clear();
    for (const pane of panes) {
      for (const [event, handler] of pane.handlers) {
        try { pane.gl.off(event, handler); } catch { /* map may already be disposed */ }
      }
      try {
        // State belongs to the underlying renderer, NOT the atlas source.
        if (pane.sourceId) {
          pane.gl.removeFeatureState({ source: pane.sourceId, sourceLayer: PMTILES_SOURCE_LAYER });
        }
      } catch (error) {
        onError?.(new Error(`Could not clear prediction feature-state: ${error.message}`));
      }
      for (const layer of [pane.fill, pane.line]) {
        if (layer) {
          try { pane.map.layers.remove(layer); } catch { /* map may already be disposed */ }
        }
      }
      if (pane.source) {
        try { pane.map.sources.remove(pane.source); } catch { /* same teardown race */ }
      }
    }
    if (!ready) rejectReady(new DOMException("Prediction rendering cancelled.", "AbortError"));
  }

  function fail(error) {
    if (disposed) return;
    const failure = new Error(`Prediction renderer failed: ${error?.message || error}`);
    rejectReady(failure);
    onError?.(failure);
    dispose();
  }

  function hydrate() {
    const ids = new Set();
    for (const pane of panes) {
      const features = pane.gl.queryRenderedFeatures(undefined, { layers: pane.fillIds });
      for (const feature of features) {
        if (feature.source !== pane.sourceId) {
          throw new Error("A prediction layer returned an unrelated map source.");
        }
        const row = byId.get(feature.id);
        if (row === undefined) throw new Error("Footprint and prediction row IDs do not match.");
        const overtureId = feature.properties?.overture_id;
        if (typeof overtureId !== "string" || !overtureId.trim() ||
            overtureId !== attrs.overtureIds[row]) {
          throw new Error("Footprint and prediction Overture IDs do not match.");
        }
        if (!locations.has(feature.id)) {
          const location = featureCentroid(feature.geometry);
          if (location) locations.set(feature.id, location);
        }
        ids.add(feature.id);
      }
    }
    // Discover sources on BOTH panes before deduplication or any state write.
    // Also update previously seen IDs, e.g. deselecting an off-screen building.
    for (const pane of panes) for (const id of pane.written.keys()) ids.add(id);
    paintIds(ids);
  }

  function paintIds(ids) {
    for (const id of ids) {
      const state = {
        cls: CLASS_CODES[(presentation?.classes || attrs.classes)[byId.get(id)]],
        edited: presentation?.editedIds?.has(id) || false,
        dim: presentation?.dimmedIds?.has(id) || false,
        selected: presentation?.selectedId === id,
      };
      const fingerprint = JSON.stringify(state);
      for (const pane of panes) {
        // Writing identical state on every idle event would create a perpetual
        // render -> idle -> state-write loop. GL retains state across tile
        // eviction, so only newly seen IDs need a write in this generation.
        if (pane.written.get(id) === fingerprint) continue;
        pane.gl.setFeatureState({
          source: pane.sourceId, sourceLayer: PMTILES_SOURCE_LAYER, id,
        }, state);
        pane.written.set(id, fingerprint);
      }
    }
  }

  function update() {
    if (disposed) return;
    try {
      for (const pane of panes) {
        pane.sourceId ||= discoverVectorSourceId(
          pane.gl, pane.previousSources, pane.requestedSourceId, pane.sourceUrl,
        );
        if (!pane.sourceId) return;
        pane.fillIds = discoverFillLayerIds(pane.gl, pane.sourceId);
        if (!pane.fillIds.length || !pane.gl.isSourceLoaded(pane.sourceId)) return;
      }
      hydrate();
      if (!ready) {
        ready = true;
        clearTimeout(timer);
        resolveReady();
      }
    } catch (error) {
      fail(error);
    }
  }

  function scheduleHydrate() {
    if (disposed || frame !== null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      update();
    });
  }

  try {
    for (const [index, map] of maps.entries()) {
      const gl = findGlMap(map);
      const methods = [
        "getStyle", "setFeatureState", "removeFeatureState", "queryRenderedFeatures",
        "isSourceLoaded", "on", "off",
      ];
      if (!gl || methods.some((name) => typeof gl[name] !== "function")) {
        throw new Error(`${PANE_IDS[index]} map has no usable feature-state renderer.`);
      }
      const prefix = `visualizer${PANE_IDS[index]}`;
      const pane = {
        map, gl, previousSources: new Set(Object.keys(gl.getStyle()?.sources || {})),
        sourceId: null, handlers: [], fillIds: [], written: new Map(),
        requestedSourceId: `${prefix}Buildings`, sourceUrl: `pmtiles://${archiveKey}`,
        key: index === 0 ? "primary" : "secondary",
      };
      panes.push(pane);
      const onRendererError = (event) => {
        if (isOptionalAzureBasemapAuthError(event)) return;
        fail(event.error || new Error("Map tile loading failed."));
      };
      for (const [event, handler] of [
        ["sourcedata", scheduleHydrate], ["moveend", scheduleHydrate],
        ["idle", scheduleHydrate], ["error", onRendererError],
      ]) {
        gl.on(event, handler);
        pane.handlers.push([event, handler]);
      }
      pane.source = new atlas.source.VectorTileSource(pane.requestedSourceId, {
        type: "vector", url: pane.sourceUrl,
      });
      map.sources.add(pane.source);
      if (disposed) break;
      pane.fill = new atlas.layer.PolygonLayer(pane.source, `${prefix}FootprintFill`, {
        sourceLayer: PMTILES_SOURCE_LAYER, fillColor: fillColorExpression(),
        fillOpacity: ["case", ["boolean", ["feature-state", "dim"], false], 0.1, 0.55],
      });
      map.layers.add(pane.fill);
      if (disposed) break;
      pane.line = new atlas.layer.LineLayer(pane.source, `${prefix}FootprintOutline`, {
        sourceLayer: PMTILES_SOURCE_LAYER, strokeColor: strokeColorExpression(FALLBACK_COLORS),
        strokeWidth: ["case", ["boolean", ["feature-state", "selected"], false], 4,
          ["boolean", ["feature-state", "edited"], false], 2.5, 1],
      });
      map.layers.add(pane.line);
      if (disposed) break;
    }
    if (!disposed) {
      timer = setTimeout(() => fail(new Error("Both footprint sources did not finish loading.")), RENDERER_TIMEOUT_MS);
      // Defer until both panes exist, including when the SDK completes synchronously.
      queueMicrotask(update);
    }
  } catch (error) {
    fail(error);
  }

  return {
    ready: readyPromise,
    dispose,
    onDispose(cleanup) {
      disposers.add(cleanup);
      return () => disposers.delete(cleanup);
    },
    getPanes() {
      return disposed ? [] : panes.map((pane) => ({ key: pane.key, map: pane.map, fillLayer: pane.fill }));
    },
    getKnownLocation(id) { return locations.get(id); },
    query(paneKey, box) {
      if (disposed || !ready) return [];
      const pane = panes.find((value) => value.key === paneKey);
      if (!pane) return [];
      return pane.gl.queryRenderedFeatures(box, { layers: pane.fillIds })
        .filter((feature) => feature.source === pane.sourceId && byId.has(feature.id));
    },
    setPresentation(next) {
      if (disposed) return;
      if (next && (next.classes?.length !== attrs.n || next.classes.some((cls) => !CLASS_CODES[cls]))) {
        fail(new Error("Invalid prediction presentation."));
        return;
      }
      const previous = presentation;
      presentation = next;
      if (ready && previous && next && previous.classes === next.classes &&
          previous.editedIds === next.editedIds && previous.dimmedIds === next.dimmedIds) {
        // Keyboard review changes just two selection flags, not every class.
        try {
          paintIds(new Set([previous.selectedId, next.selectedId].filter((id) => byId.has(id))));
        } catch (error) { fail(error); }
      } else if (ready) update();
    },
    setVisible(visible) {
      if (disposed) return;
      try {
        for (const pane of panes) {
          pane.fill.setOptions({ visible });
          pane.line.setOptions({ visible });
        }
        // Hidden layers do not appear in rendered-feature queries. Rehydrate
        // when they are shown again so newly visible tiles acquire classes.
        if (visible) scheduleHydrate();
      } catch (error) { fail(error); }
    },
    setColors(colors) {
      if (disposed) return;
      try {
        for (const pane of panes) {
          pane.fill.setOptions({ fillColor: fillColorExpression(colors) });
          pane.line.setOptions({ strokeColor: strokeColorExpression(colors) });
        }
      } catch (error) { fail(error); }
    },
  };
}
