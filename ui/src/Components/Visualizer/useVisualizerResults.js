// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useCallback, useEffect, useRef, useState } from "react";
import { buildUrl } from "../../util/api";
import { buildVisualizerResultsUrl } from "./predictionResults.js";
import { loadPredictionArtifacts } from "./predictionArtifactLoader.js";
import { requestPredictionJson } from "./predictionHttp.js";
import { validateSelectedSource } from "./predictionVersions.js";

export default function useVisualizerResults(ids) {
  const endpoint = buildVisualizerResultsUrl(ids);
  const [response, setResponse] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [switchState, setSwitchState] = useState(null);
  const runRef = useRef(0);
  const switchAbortRef = useRef(null);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const key = `${endpoint}:${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    const run = {};
    runRef.current = run;
    requestPredictionJson(buildUrl(endpoint), { signal: controller.signal }).then((results) => {
      validateSelectedSource(results);
      if (run === runRef.current) setResponse({ key, results });
    }).catch((error) => {
      if (!controller.signal.aborted && run === runRef.current) setResponse({ key, error: error.message });
    });
    return () => {
      runRef.current = null;
      controller.abort();
      switchAbortRef.current?.abort();
    };
  }, [endpoint, key]);

  const loadVersion = useCallback(async (version, expectedRevision) => {
    switchAbortRef.current?.abort();
    const controller = new AbortController();
    switchAbortRef.current = controller;
    const run = {};
    runRef.current = run;
    setSwitchState({ key, version, loading: true });
    let phase = "metadata";
    try {
      const url = `${endpoint}&version=${version}`;
      const results = validateSelectedSource(
        await requestPredictionJson(buildUrl(url), { signal: controller.signal }), version, expectedRevision,
      );
      phase = "attributes";
      if (!results.predictionsReady || results.buildingCount === 0) {
        throw new Error(results.predictionsReadiness?.detail || "This version has no renderable prediction attributes.");
      }
      const data = await loadPredictionArtifacts(results, buildUrl, controller.signal);
      if (run !== runRef.current) throw new DOMException("Version switch cancelled.", "AbortError");
      const preloaded = { results, ...data };
      // Metadata and validated attributes are adopted as ONE source snapshot.
      setResponse({ key, results, preloaded });
      setSwitchState(null);
      return { results, ...data };
    } catch (error) {
      if (run === runRef.current && !controller.signal.aborted) {
        setSwitchState({ key, version, error: error.message, phase });
      }
      throw error;
    }
  }, [endpoint, key]);

  const current = response?.key === key ? response : {};
  return {
    ...current, retry, loadVersion,
    switchState: switchState?.key === key ? switchState : null,
  };
}
