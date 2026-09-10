// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useCallback, useEffect, useState } from "react";
import { buildUrl } from "../../util/api";
import { buildVisualizerResultsUrl } from "./predictionResults.js";
import { fetchArtifactBuffer, MAX_ATTRIBUTES_BYTES } from "./predictionArtifactLoader.js";

export default function useVisualizerResults(ids) {
  const [attempt, setAttempt] = useState(0);
  const [response, setResponse] = useState(null);
  const endpoint = buildVisualizerResultsUrl(ids);
  const key = JSON.stringify([endpoint, attempt]);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const buffer = await fetchArtifactBuffer(buildUrl(endpoint), {
          signal: controller.signal, maxBytes: MAX_ATTRIBUTES_BYTES,
        });
        const results = JSON.parse(new TextDecoder().decode(buffer));
        if (!results || typeof results !== "object" || Array.isArray(results)) {
          throw new Error("The server returned invalid results.");
        }
        if (!controller.signal.aborted) setResponse({ key, results });
      } catch (error) {
        if (!controller.signal.aborted) setResponse({ key, error: error.message });
      }
    }
    load();
    return () => controller.abort();
  }, [endpoint, key]);

  return {
    results: response?.key === key ? response.results : null,
    error: response?.key === key ? response.error : "",
    retry,
  };
}
