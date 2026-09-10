// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Map lifecycle extracted from PR136: distinct DOM/map references, two ready
// events, optional rasters and SwipeMap disposal before disposing either map.
import { useEffect, useState } from "react";
import { getAzureMapsAuthOptions, isAzureMapsPlaceholder } from "../../util/azureMapsAuth";
import { waitForMapReady } from "../InteractiveLabeler/interactiveLabelerLoading.js";
import { hasRasterLayer } from "./predictionResults.js";

function addRaster(atlas, map, block, id, visible = true) {
  if (!hasRasterLayer(block)) return;
  map.layers.add(new atlas.layer.TileLayer({
    tileUrl: block.url, minZoom: 1, maxZoom: 22, bounds: block.bounds,
    attribution: block.attribution, visible,
  }, id));
}

export function validBounds(bounds) {
  return Array.isArray(bounds) && bounds.length === 4 &&
    bounds.every(Number.isFinite) && bounds[0] <= bounds[2] && bounds[1] <= bounds[3];
}

export default function useVisualizerMaps({ results, primaryContainerRef, secondaryContainerRef }) {
  const [state, setState] = useState(null);

  useEffect(() => {
    if (!results) return;
    const controller = new AbortController();
    const maps = [];
    const errorHandlers = [];
    const beforeDispose = new Set();
    const registerCleanup = (cleanup) => {
      beforeDispose.add(cleanup);
      return () => beforeDispose.delete(cleanup);
    };
    let swipe;
    let zoom;
    let disposed = false;
    const containers = [primaryContainerRef.current, secondaryContainerRef.current];
    const reportError = (event) => {
      if (!controller.signal.aborted) {
        setState({
          results,
          error: event?.error?.message || event?.message || "Azure Maps failed to load.",
        });
      }
    };
    const dispose = () => {
      if (disposed) return;
      disposed = true;
      controller.abort();
      // Footprint feature-state must be cleared while the renderers still
      // exist, before React gets to the dependent hook's own cleanup.
      for (const cleanup of beforeDispose) cleanup();
      beforeDispose.clear();
      try { swipe?.dispose(); } catch { /* partial SDK initialization */ }
      maps.forEach((map, index) => {
        map.events.remove("error", errorHandlers[index]);
        try { map.dispose(); } catch { /* partial SDK initialization */ }
      });
      // SwipeMap leaves this inline clip behind even after dispose().
      for (const element of containers) if (element) element.style.clip = "";
    };

    async function initialize() {
      try {
        const atlas = window.atlas;
        if (!atlas?.Map || !atlas?.SwipeMap) throw new Error("Azure Maps could not be initialized. Reload the page to try again.");
        const ready = containers.map((container, index) => {
          const map = new atlas.Map(container, {
            style: isAzureMapsPlaceholder ? "blank" : "satellite",
            authOptions: getAzureMapsAuthOptions(),
          });
          maps.push(map);
          const onError = (event) => reportError(event);
          errorHandlers.push(onError);
          map.events.add("error", onError);
          const promise = waitForMapReady(map, {
            signal: controller.signal,
            onReady: () => {
              map.setUserInteraction({
                dragRotateInteraction: false, scrollZoomInteraction: true,
                pinchZoomInteraction: true, pinchRotateInteraction: false,
              });
              map.setCamera({ bearing: 0 });
              addRaster(atlas, map, index === 0 ? results.preDisasterImagery : results.postDisasterImagery,
                index === 0 ? "preDisasterImagery" : "postDisasterImagery");
              // Vectors are the primary result; rasters remain opt-in context.
              addRaster(atlas, map, results.predictedDamageLayer, "predictedDamageLayer", false);
              addRaster(atlas, map, results.predictionsLayer, "predictionsLayer", false);
              if (Array.isArray(results.studyArea) && results.studyArea.length) {
                const source = new atlas.source.DataSource();
                map.sources.add(source);
                source.add({ type: "FeatureCollection", features: results.studyArea });
                map.layers.add(new atlas.layer.LineLayer(source, undefined, {
                  strokeColor: "white", strokeWidth: 2,
                }));
              }
            },
          });
          // A later map constructor can fail before Promise.all is reached.
          promise.catch(() => {});
          return promise;
        });
        await Promise.all(ready);
        controller.signal.throwIfAborted();
        swipe = new atlas.SwipeMap(maps[0], maps[1]);
        zoom = new atlas.control.ZoomControl();
        maps[0].controls.add(zoom, { position: "bottom-left" });
        setState({ results, maps, swipe, zoom, registerCleanup });
      } catch (error) {
        if (!controller.signal.aborted) {
          reportError(error);
          dispose();
        }
      }
    }
    initialize();
    return dispose;
  }, [results, primaryContainerRef, secondaryContainerRef]);

  return state?.results === results ? state : {};
}
