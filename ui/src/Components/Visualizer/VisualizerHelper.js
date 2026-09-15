// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export function getStudyAreaCameraOptions(studyArea, duration = 700) {
  const bounds = studyArea?.[0]?.bbox;
  if (!Array.isArray(bounds) || bounds.length !== 4 || !bounds.every(Number.isFinite)) {
    return null;
  }
  return {
    bounds: [...bounds],
    type: duration > 0 ? "fly" : "jump",
    duration,
    padding: 100,
  };
}

// Both SDK maps must be ready before fitting the synchronized cameras. Wait
// one frame for layout, and initialize only once even if ready is repeated.
export function whenVisualizerMapsReady(
  maps,
  initialize,
  requestFrame = requestAnimationFrame,
  cancelFrame = cancelAnimationFrame
) {
  const ready = new Set();
  let active = true;
  let scheduled = false;
  let frame = null;
  const handlers = maps.map((map) => () => {
    if (!active || scheduled) return;
    ready.add(map);
    if (ready.size === maps.length) {
      scheduled = true;
      frame = requestFrame(() => {
        frame = null;
        if (active) initialize();
      });
    }
  });
  maps.forEach((map, index) => map.events.add("ready", handlers[index]));

  return () => {
    active = false;
    if (frame !== null) cancelFrame(frame);
    maps.forEach((map, index) => map.events.remove("ready", handlers[index]));
  };
}
