// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Pure decision logic for the Prediction Editor's swipe comparison map.
//
// Nothing here touches the DOM, React, or Azure Maps, so every rule the
// editor relies on — which comparison the analyst gets, what the panes are
// called, and where a keyboard shortcut puts the divider — is unit-testable
// in predictionClassify.test.js.
//
// Geometry note that the copy in this file depends on (and that a previous
// PR shipped backwards): atlas.SwipeMap shows its PRIMARY map on the LEFT of
// the divider and clips its SECONDARY to reveal it on the RIGHT. The editor
// wires the comparison map (pre-event imagery, or the plain basemap) as the
// PRIMARY and the editable post-event map as the SECONDARY. So:
//
//   divider fully LEFT  -> the post-event (editing) map fills the view
//   divider fully RIGHT -> the comparison (pre-event / basemap) map fills it

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
 * Which comparison applies for a layer's imagery block, as returned by
 * GetLayerLabelingToolData (`layerData.imagery`).
 *
 * The post-event tiles are what the editable map draws its footprints over,
 * so without them there is no meaningful comparison and the toggle is not
 * offered at all. Pre-event tiles, when present, replace the basemap on the
 * comparison pane.
 */
export function resolveSwipeMode(imagery) {
  const post = cleanUrl(imagery?.postEventTileUrl);
  if (!post) return SWIPE_MODE_NONE;
  return cleanUrl(imagery?.preEventTileUrl)
    ? SWIPE_MODE_PRE_POST
    : SWIPE_MODE_BASEMAP_POST;
}

/** True when the editor should show the swipe toggle. */
export function isSwipeAvailable(mode) {
  return mode === SWIPE_MODE_PRE_POST || mode === SWIPE_MODE_BASEMAP_POST;
}

/**
 * The tile URL the comparison pane should draw, or "" when it should just
 * show its own basemap. Only the pre/post mode has an imagery overlay.
 */
export function swipeComparisonTileUrl(imagery, mode) {
  return mode === SWIPE_MODE_PRE_POST ? cleanUrl(imagery?.preEventTileUrl) : "";
}

/** Toggle label — the user must be able to see which comparison they get. */
export function swipeToggleLabel(mode) {
  if (mode === SWIPE_MODE_PRE_POST) return "Swipe: pre-event vs post-event";
  if (mode === SWIPE_MODE_BASEMAP_POST) return "Swipe: basemap vs post-event";
  return "Swipe comparison unavailable";
}

/** Badge over the left (comparison) pane. */
export function swipeLeftPaneLabel(mode) {
  if (mode === SWIPE_MODE_PRE_POST) return "Pre-event imagery";
  if (mode === SWIPE_MODE_BASEMAP_POST) return "Basemap";
  return "";
}

/** Badge over the right (editable, post-event) pane. */
export function swipeRightPaneLabel(mode) {
  return isSwipeAvailable(mode) ? "Post-event imagery" : "";
}

/**
 * One-line explanation under the toggle. Direction matters: the comparison
 * map is the PRIMARY and sits LEFT of the divider, so dragging the divider
 * left uncovers MORE post-event imagery and dragging it right uncovers more
 * of the comparison pane.
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
