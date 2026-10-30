// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef, useState } from "react";
import { buildUrl } from "../../util/api";
import { createTileCredentialRefreshController } from "../../util/tileCredentialRefresh";
import { buildVisualizerResultsUrl, pickTileLayers, sameTileSource } from "./predictionResults.js";
import { requestPredictionJson } from "./predictionHttp.js";

/**
 * Keeps the signed tile URLs of the displayed prediction version fresh.
 * The refresh re-requests the same version and exposes only the tile layers
 * as an override, so results, selection, edits and the maps are untouched.
 * The controller lives as long as one results snapshot: switching versions
 * disposes it, which also drops any refresh still in flight.
 */
export default function useVisualizerTileRefresh(ids, results, applierRef) {
  const [override, setOverride] = useState(null);
  // The snapshot whose refresh failed; a newer snapshot has fresh credentials.
  const [failed, setFailed] = useState(null);
  const controllerRef = useRef(null);
  const endpoint = buildVisualizerResultsUrl(ids);

  useEffect(() => {
    if (!results?.tileCredentialExpiresAt) return undefined;
    const controller = createTileCredentialRefreshController({
      fetchCredentials: () => requestPredictionJson(
        buildUrl(`${endpoint}&version=${results.predictionVersion ?? 0}`),
      ),
      applyCredentials: (next) => {
        if (!sameTileSource(results, next)) throw new Error("The prediction source changed.");
        const layers = pickTileLayers(next);
        // Apply to the live layers first so a failure reaches the retry path.
        if (!applierRef?.current) throw new Error("The maps are not ready.");
        applierRef.current(layers);
        setOverride({ base: results, layers });
      },
      onError: () => setFailed(results),
      onSuccess: () => setFailed(null),
    });
    controllerRef.current = controller;
    controller.start(results);
    return () => {
      controller.dispose();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [endpoint, results, applierRef]);

  // An override only applies to the snapshot it refreshed; a newer snapshot carries fresher URLs.
  const layers = override && override.base === results ? override.layers : null;
  return {
    tileLayers: layers,
    tileRefreshFailed: !!results && failed === results,
    retryTileRefresh: () => controllerRef.current?.refresh() || Promise.resolve(false),
  };
}
