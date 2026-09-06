// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { createPredictionDownloadOperation } from "../Visualizer/predictionDownloadOperation.js";
import { downloadPrediction } from "../Visualizer/predictionDownload.js";
import { requestPredictionJson } from "../Visualizer/predictionHttp.js";
import { validateSelectedSource } from "../Visualizer/predictionVersions.js";
import { hasEditedPredictions } from "./ModelResultsMenuHelper.js";

// Cached rows cannot decide whether another analyst has saved an edit. Read
// fresh metadata before offering versions; genuinely raw-only results keep
// their one-click download, without opening a pointless version dialog.
export function createModelResultsDownload({
  rawUrl, onChooseVersion, onChange, fetchResponse, download = downloadPrediction,
}) {
  return createPredictionDownloadOperation(async (resultsUrl, version, { signal }) => {
    const source = validateSelectedSource(await requestPredictionJson(resultsUrl, {
      signal, fetchResponse,
    }));
    signal.throwIfAborted();
    if (hasEditedPredictions(source)) {
      onChooseVersion();
      return;
    }
    await download(rawUrl, version, { signal });
  }, onChange);
}
