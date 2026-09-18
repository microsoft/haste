// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's artifact/renderer boundary, with eager read-only artifact semantics.
import { useEffect, useState } from "react";
import { buildUrl } from "../../util/api";
import { loadPredictionArtifacts } from "./predictionArtifactLoader.js";
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
        const artifacts = await loadPredictionArtifacts(results, buildUrl, signal);
        signal.throwIfAborted();
        setLoaded({ key, results, ...artifacts });
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
