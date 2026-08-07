// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useState } from "react";

export function useImagePreload(url) {
  const [state, setState] = useState({ url: null, status: "empty" });

  useEffect(() => {
    if (!url) {
      return undefined;
    }

    let isActive = true;
    const image = new Image();

    image.onload = () => {
      if (isActive) setState({ url, status: "loaded" });
    };
    image.onerror = () => {
      if (isActive) setState({ url, status: "error" });
    };
    image.src = url;

    return () => {
      isActive = false;
      image.onload = null;
      image.onerror = null;
    };
  }, [url]);

  return {
    isLoading: Boolean(url) && (state.url !== url || state.status === "loading"),
    loadedUrl: state.url === url && state.status === "loaded" ? url : null,
  };
}