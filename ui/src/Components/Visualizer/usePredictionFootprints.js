// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Read-only wiring around PR136's two-renderer source/layer lifecycle.
import { useEffect, useRef, useState } from "react";
import { tokens } from "@fluentui/react-components";
import { createPredictionRenderer, resolveMapColors } from "./predictionFootprintMap.js";

const COLOR_TOKENS = {
  damaged: tokens.colorStatusDangerBackground3,
  notDamaged: tokens.colorStatusSuccessBackground3,
  unknown: tokens.colorNeutralForeground3,
  pending: tokens.colorNeutralBackground5,
  outline: tokens.colorNeutralStrokeAccessible,
};

export default function usePredictionFootprints({ maps, registerCleanup, artifacts, visible, themeHostRef, isDark, palette }) {
  const rendererRef = useRef(null);
  const [state, setState] = useState(null);
  const { key, archiveKey, attrs } = artifacts;

  useEffect(() => {
    if (!maps || !archiveKey || !attrs) return;
    let active = true;
    let renderer;
    let unregister;
    const failed = (error) => {
      if (active) setState({ key, maps, error: error.message });
    };
    try {
      renderer = createPredictionRenderer({
        atlas: window.atlas, maps, archiveKey, attrs, onError: failed,
      });
      rendererRef.current = renderer;
      unregister = registerCleanup?.(() => renderer.dispose());
      renderer.ready.then(() => {
        if (active) setState({ key, maps, ready: true });
      }).catch(failed);
    } catch (error) {
      queueMicrotask(() => failed(error));
    }
    return () => {
      active = false;
      unregister?.();
      renderer?.dispose();
      rendererRef.current = null;
    };
  }, [maps, registerCleanup, key, archiveKey, attrs]);

  const current = state?.key === key && state?.maps === maps && !!attrs;
  const layersReady = current && state.ready === true;

  useEffect(() => {
    rendererRef.current?.setVisible(visible);
  }, [visible, maps, key, archiveKey, layersReady]);

  useEffect(() => {
    const element = themeHostRef.current;
    if (!element) return;
    const style = window.getComputedStyle(element);
    rendererRef.current?.setColors(resolveMapColors(COLOR_TOKENS, (name) => style.getPropertyValue(name)));
  }, [isDark, palette, themeHostRef, maps, key, archiveKey, layersReady]);

  return { layersReady, error: current ? state.error : "" };
}
