// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import { buildUrl } from "../../util/api";
import { requestPredictionJson } from "../Visualizer/predictionHttp.js";
import { validateSelectedSource, versionEndpoint } from "../Visualizer/predictionVersions.js";
import usePredictionVersionManifest from "../Visualizer/usePredictionVersionManifest";

export default function usePredictionReport(action, ids) {
  const routeKey = JSON.stringify(ids);
  const [selection, setSelection] = useState(null);
  const selectedVersion = selection?.routeKey === routeKey ? selection.version : null;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState(null);
  const manifest = usePredictionVersionManifest(ids);
  // Omit initially: the SERVER resolves latest-for-current-generation. An
  // initially empty/stale model-row version list must not force raw output.
  const endpoint = versionEndpoint(action, ids, selectedVersion);
  const key = `${endpoint}:${attempt}`;
  useEffect(() => {
    const controller = new AbortController();
    requestPredictionJson(buildUrl(endpoint), { signal: controller.signal }).then((report) => {
      validateSelectedSource(report, selectedVersion);
      if (!controller.signal.aborted) setState({ key, report });
    }).catch((error) => {
      if (!controller.signal.aborted) setState({ key, error: error.message });
    });
    return () => controller.abort();
  }, [endpoint, key, selectedVersion]);
  const current = state?.key === key ? state : {};
  return {
    report: current.report, error: current.error, loading: state?.key !== key,
    version: selectedVersion ?? current.report?.predictionVersion ?? 0,
    selectVersion: (version) => setSelection({ routeKey, version }),
    retry: () => setAttempt((value) => value + 1),
    manifest,
  };
}
