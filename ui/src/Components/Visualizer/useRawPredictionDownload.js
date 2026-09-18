// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useMemo, useState } from "react";
import { downloadPrediction } from "./predictionDownload.js";
import { createPredictionDownloadOperation } from "./predictionDownloadOperation.js";

export default function useRawPredictionDownload(url) {
  const [state, setState] = useState(null);
  const operation = useMemo(() => createPredictionDownloadOperation(
    downloadPrediction, (next) => setState({ url, ...next }),
  ), [url]);
  useEffect(() => () => operation.cancel(), [operation]);
  return {
    loading: state?.url === url && state.loading,
    download: () => operation.run(url),
  };
}
