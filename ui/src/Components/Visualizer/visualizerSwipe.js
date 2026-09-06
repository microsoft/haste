// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Read-only swipe decisions from PR136. Primary is LEFT, secondary RIGHT.
import { hasRasterLayer } from "./predictionResults.js";

// Matches the mobile Info/switch panel and Bootstrap's desktop `lg` chrome.
// Using 1200px here would leave 992–1199px with neither comparison control.
export const RESULTS_DESKTOP_MIN_WIDTH = 992;

export function isMobileResultsLayout(viewportWidth) {
  return viewportWidth < RESULTS_DESKTOP_MIN_WIDTH;
}

export function swipeLeftPaneLabel(results) {
  return hasRasterLayer(results?.preDisasterImagery) ? "Pre-event imagery" : "Basemap";
}

export function swipeRightPaneLabel(results) {
  return hasRasterLayer(results?.postDisasterImagery) ? "Post-event imagery" : "Basemap";
}

export function dividerPositionForKey(key, width) {
  if (typeof key !== "string" || !Number.isFinite(width) || width <= 0) return null;
  switch (key.toLowerCase()) {
    case "a": return 0;
    case "s": return width / 2;
    case "d": return width;
    default: return null;
  }
}
