// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export function getTourCardStyle(spot, viewportWidth, viewportHeight) {
  const viewportMargin = 16;
  const cardGap = 14;
  const preferredCardHeight = 280;
  const cardWidth = Math.min(340, viewportWidth - viewportMargin * 2);
  const targetBottom = spot.top + spot.height;
  const spaceBelow =
    viewportHeight - targetBottom - cardGap - viewportMargin;
  const spaceAbove = spot.top - cardGap - viewportMargin;
  const style = {
    position: "fixed",
    width: cardWidth,
    left: Math.max(
      viewportMargin,
      Math.min(spot.left - 8, viewportWidth - cardWidth - viewportMargin)
    ),
  };

  if (spaceBelow >= preferredCardHeight) {
    style.top = targetBottom + cardGap;
    style.maxHeight = viewportHeight - style.top - viewportMargin;
  } else if (spaceAbove >= preferredCardHeight) {
    style.bottom = viewportHeight - spot.top + cardGap;
    style.maxHeight = spaceAbove;
  } else {
    style.top = Math.max(
      viewportMargin,
      Math.min(
        spot.top + cardGap,
        viewportHeight - preferredCardHeight - viewportMargin
      )
    );
    style.maxHeight = viewportHeight - style.top - viewportMargin;
  }

  return style;
}