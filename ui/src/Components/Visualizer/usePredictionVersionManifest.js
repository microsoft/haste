// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import { buildUrl } from "../../util/api";
import { requestPredictionJson } from "./predictionHttp.js";
import { validateVersionManifest, versionEndpoint } from "./predictionVersions.js";

export default function usePredictionVersionManifest(ids) {
  const endpoint = versionEndpoint("GetEditedPredictionVersions", ids);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState(null);
  const key = `${endpoint}:${attempt}`;
  useEffect(() => {
    const controller = new AbortController();
    requestPredictionJson(buildUrl(endpoint), { signal: controller.signal }).then((data) => {
      validateVersionManifest(data.versions);
      if (!controller.signal.aborted) setState({ key, data });
    }).catch((error) => {
      if (!controller.signal.aborted) setState({ key, error: error.message });
    });
    return () => controller.abort();
  }, [endpoint, key]);
  return {
    ...(state?.key === key ? state : {}),
    loading: state?.key !== key,
    retry: () => setAttempt((value) => value + 1),
  };
}
