// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's artifact/renderer boundary, with eager read-only artifact semantics.
import { useEffect, useState } from "react";
import { PMTiles } from "pmtiles";
import { buildUrl } from "../../util/api";
import { getPmtilesProtocol, InMemoryPMTilesSource } from "../../util/pmtiles.js";
import { fetchArtifactBuffer, loadPredictionAttributes } from "./predictionArtifactLoader.js";
import { predictionRenderKey } from "./predictionResults.js";

export default function usePredictionArtifacts(results) {
  const [loaded, setLoaded] = useState(null);
  const key = predictionRenderKey(results);

  useEffect(() => {
    if (!results || results.predictionsReady !== true || results.buildingCount === 0) return;
    const controller = new AbortController();
    const { signal } = controller;
    async function load() {
      try {
        const { attrs, archiveUrl } = await loadPredictionAttributes(results, buildUrl, signal);
        const protocol = getPmtilesProtocol();
        let archive = protocol.get(archiveUrl);
        if (!archive) {
          const buffer = await fetchArtifactBuffer(archiveUrl, { signal });
          signal.throwIfAborted();
          archive = new PMTiles(new InMemoryPMTilesSource(archiveUrl, buffer));
        }
        // Validate the archive before declaring a successful download. Its
        // bounds also locate embedding results without a labeling study area.
        const header = await archive.getHeader();
        signal.throwIfAborted();
        protocol.add(archive);
        setLoaded({
          key, results, attrs, archiveKey: archiveUrl,
          bounds: [header.minLon, header.minLat, header.maxLon, header.maxLat],
        });
      } catch (error) {
        if (!signal.aborted) setLoaded({
          key, results,
          error: error.status === 404
            ? "The image layer's footprint tiles are missing. Retry after layer processing finishes."
            : error.message,
        });
      }
    }
    load();
    return () => controller.abort();
  }, [results, key]);

  // Never expose the previous generation while its replacement downloads.
  return loaded?.key === key && loaded.results === results &&
    results?.predictionsReady === true && results?.buildingCount !== 0
    ? loaded
    : { key };
}
