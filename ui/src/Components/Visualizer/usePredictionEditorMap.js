// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef } from "react";
import { attachPredictionEditing } from "./predictionEditorMap.js";

export default function usePredictionEditorMap({ renderer, enabled, interactive, presentation, paint, reset, boxRef, onError }) {
  const actions = useRef({ paint, reset, onError, interactive });
  useEffect(() => { actions.current = { paint, reset, onError, interactive }; }, [paint, reset, onError, interactive]);
  useEffect(() => {
    if (!renderer) return;
    renderer.setPresentation(enabled ? presentation : null);
  }, [renderer, enabled, presentation]);
  useEffect(() => {
    if (!renderer || !enabled) return;
    try {
      return attachPredictionEditing(renderer, {
        paint: (ids) => actions.current.paint(ids),
        reset: (id) => actions.current.reset(id),
        onError: (error) => actions.current.onError(error),
        canInteract: () => actions.current.interactive,
        boxElement: boxRef.current,
      });
    } catch (error) {
      queueMicrotask(() => actions.current.onError(error));
    }
  }, [renderer, enabled, boxRef]);
}
