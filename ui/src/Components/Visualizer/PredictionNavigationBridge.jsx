// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext, useLayoutEffect } from "react";
import PropTypes from "prop-types";
import { UNSAFE_NavigationContext } from "react-router-dom";
import { installPredictionNavigation } from "./predictionNavigation.js";

export default function PredictionNavigationBridge({ children }) {
  const { navigator } = useContext(UNSAFE_NavigationContext);
  // Child layout effects run before BrowserRouter's parent layout effect,
  // which subscribes to this history. Routes and authentication are unchanged.
  useLayoutEffect(() => installPredictionNavigation(navigator), [navigator]);
  return children;
}
PredictionNavigationBridge.propTypes = { children: PropTypes.node.isRequired };
