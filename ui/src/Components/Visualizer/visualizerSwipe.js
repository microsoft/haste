// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Pure decision logic for the results view's swipe map.
//
// Nothing here touches the DOM, React, or Azure Maps, so the rules the
// results page relies on — which comparison the analyst is looking at, what
// the panes are called, and where a keyboard shortcut puts the divider — are
// unit-testable in predictionClassify.test.js.
//
// Geometry note that the copy in this file depends on (and that a previous PR
// shipped backwards): atlas.SwipeMap shows its PRIMARY map on the LEFT of the
// divider and clips its SECONDARY to reveal it on the RIGHT. The results page
// wires the pre-event map (or the plain basemap, when the layer has no
// pre-event imagery) as the PRIMARY and the post-event map — the one carrying
// the predicted damage raster and the editable footprints — as the SECONDARY.
// So:
//
//   divider fully LEFT  -> the post-event map fills the view
//   divider fully RIGHT -> the pre-event / basemap map fills it

// Pre-event imagery on the left, post-event imagery on the right.
export const SWIPE_MODE_PRE_POST = "prePost";
// The layer has no pre-event imagery: compare the basemap against post-event.
export const SWIPE_MODE_BASEMAP_POST = "basemapPost";
// Nothing worth comparing (no post-event imagery), so no swipe is offered.
export const SWIPE_MODE_NONE = "none";

// Keys that snap the divider, in left → centre → right order.
export const SWIPE_DIVIDER_KEYS = ["a", "s", "d"];

function cleanUrl(value) {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Which comparison the results page is showing, from the imagery it has.
 *
 * The post-event tiles are what the predictions are drawn over, so without
 * them there is no meaningful comparison at all. Pre-event tiles, when
 * present, replace the basemap on the left-hand pane.
 *
 * Accepts either shape the app hands around: `{ preEventTileUrl,
 * postEventTileUrl }` from GetLayerLabelingToolData, or the results payload's
 * `{ preDisasterImagery, postDisasterImagery }` blocks.
 */
export function resolveSwipeMode(imagery) {
  const post = cleanUrl(
    imagery?.postEventTileUrl ?? imagery?.postDisasterImagery?.url
  );
  if (!post) return SWIPE_MODE_NONE;
  const pre = cleanUrl(
    imagery?.preEventTileUrl ?? imagery?.preDisasterImagery?.url
  );
  return pre ? SWIPE_MODE_PRE_POST : SWIPE_MODE_BASEMAP_POST;
}

/** True when there are two panes worth comparing. */
export function isSwipeAvailable(mode) {
  return mode === SWIPE_MODE_PRE_POST || mode === SWIPE_MODE_BASEMAP_POST;
}

/** Badge/label for the left (pre-event or basemap) pane. */
export function swipeLeftPaneLabel(mode) {
  if (mode === SWIPE_MODE_PRE_POST) return "Pre-event imagery";
  if (mode === SWIPE_MODE_BASEMAP_POST) return "Basemap";
  return "";
}

/** Badge/label for the right (post-event, editable) pane. */
export function swipeRightPaneLabel(mode) {
  return isSwipeAvailable(mode) ? "Post-event imagery" : "";
}

/**
 * One-line explanation of the divider, shown in edit mode. Direction matters:
 * the pre-event (or basemap) map is the PRIMARY and sits LEFT of the divider,
 * so dragging the divider left uncovers MORE post-event imagery and dragging
 * it right uncovers more of the pre-event pane.
 */
export function swipeModeHint(mode) {
  if (!isSwipeAvailable(mode)) {
    return "This layer has no post-event imagery to compare against.";
  }
  const left = swipeLeftPaneLabel(mode).toLowerCase();
  return (
    `${swipeLeftPaneLabel(mode)} sits left of the divider, post-event ` +
    `imagery right of it. Drag the divider left for more post-event, ` +
    `right for more ${left}. Editing works on both sides.`
  );
}

/**
 * Where the divider goes for a snap key, in pixels from the left edge of the
 * map area: A = hard left, S = centre, D = hard right. Returns null for any
 * other key, or when the map area has no usable width yet (atlas.SwipeMap
 * clamps to [0, width], so handing it a bad number would silently park the
 * divider at 0).
 */
export function dividerPositionForKey(key, width) {
  if (typeof key !== "string") return null;
  const normalized = key.toLowerCase();
  if (!SWIPE_DIVIDER_KEYS.includes(normalized)) return null;
  const usableWidth = Number(width);
  if (!Number.isFinite(usableWidth) || usableWidth <= 0) return null;
  if (normalized === "a") return 0;
  if (normalized === "s") return usableWidth / 2;
  return usableWidth;
}
