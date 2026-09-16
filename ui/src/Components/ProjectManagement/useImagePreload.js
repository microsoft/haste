// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";
import { preloadImage } from "./imagePreload.js";

export function useImagePreload(url) {
  const [state, setState] = useState({ url: null, status: "empty" });

  useEffect(() => {
    if (!url) {
      return undefined;
    }

    return preloadImage(url, (result) => setState({ url, ...result }));
  }, [url]);

  const isCurrent = state.url === url && !state.signal?.aborted;
  return {
    isLoading: Boolean(url) && !isCurrent,
    loadedUrl: isCurrent && state.status === "loaded" ? state.loadedUrl : null,
  };
}