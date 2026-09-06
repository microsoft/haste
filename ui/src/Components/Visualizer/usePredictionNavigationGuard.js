// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext, useLayoutEffect, useRef } from "react";
import { UNSAFE_NavigationContext } from "react-router-dom";
import { guardPredictionNavigation } from "./predictionNavigation.js";

export default function usePredictionNavigationGuard(active, confirm, beforeNavigate) {
  const { navigator } = useContext(UNSAFE_NavigationContext);
  const actionsRef = useRef({ confirm, beforeNavigate });
  useLayoutEffect(() => { actionsRef.current = { confirm, beforeNavigate }; }, [confirm, beforeNavigate]);
  useLayoutEffect(() => {
    if (!active) return;
    return guardPredictionNavigation(navigator, () => actionsRef.current.confirm(), window, () => actionsRef.current.beforeNavigate());
  }, [active, navigator]);
}
