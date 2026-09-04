// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const MAP_CONTROL_CSS =
  "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css";
const MAP_CONTROL_JS =
  "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.js";
const DRAWING_CSS =
  "https://atlas.microsoft.com/sdk/javascript/drawing/1/atlas-drawing.min.css";
const DRAWING_JS =
  "https://atlas.microsoft.com/sdk/javascript/drawing/1/atlas-drawing.min.js";
const SWIPE_JS = "/assets/js/azure-maps-swipe-map.min.js";

let controlPromise = null;
let drawingPromise = null;
let swipePromise = null;
const capabilityPromises = new Map();

function loadElement(documentRef, selector, createElement) {
  const existing = documentRef.querySelector(selector);
  if (existing?.dataset.loaded === "true") return Promise.resolve();

  const element = existing || createElement();
  return new Promise((resolve, reject) => {
    element.addEventListener(
      "load",
      () => {
        element.dataset.loaded = "true";
        resolve();
      },
      { once: true }
    );
    element.addEventListener(
      "error",
      () => {
        element.remove();
        reject(new Error(`Unable to load Azure Maps asset: ${element.src || element.href}`));
      },
      { once: true }
    );
    if (!existing) documentRef.head.appendChild(element);
  });
}

function loadStylesheet(documentRef, href) {
  return loadElement(
    documentRef,
    `link[data-azure-maps-href="${href}"]`,
    () => {
      const link = documentRef.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.dataset.azureMapsHref = href;
      return link;
    }
  );
}

function loadScript(documentRef, src) {
  return loadElement(
    documentRef,
    `script[data-azure-maps-src="${src}"]`,
    () => {
      const script = documentRef.createElement("script");
      script.src = src;
      script.async = true;
      script.dataset.azureMapsSrc = src;
      return script;
    }
  );
}

function loadMapControl(documentRef, stylesheet = null) {
  if (controlPromise) return controlPromise;
  controlPromise = Promise.all([
    stylesheet || loadStylesheet(documentRef, MAP_CONTROL_CSS),
    loadScript(documentRef, MAP_CONTROL_JS),
  ]).catch((error) => {
    controlPromise = null;
    throw error;
  });
  return controlPromise;
}

function loadDrawing(documentRef, stylesheet) {
  if (drawingPromise) return drawingPromise;
  drawingPromise = Promise.all([
    loadMapControl(documentRef),
    stylesheet || loadStylesheet(documentRef, DRAWING_CSS),
  ])
    .then(() => loadScript(documentRef, DRAWING_JS))
    .catch((error) => {
      drawingPromise = null;
      throw error;
    });
  return drawingPromise;
}

function loadSwipe(documentRef) {
  if (swipePromise) return swipePromise;
  swipePromise = loadMapControl(documentRef)
    .then(() => loadScript(documentRef, SWIPE_JS))
    .catch((error) => {
      swipePromise = null;
      throw error;
    });
  return swipePromise;
}

export function loadAzureMaps(
  documentRef = document,
  { drawing = true, swipe = true } = {}
) {
  const capabilityKey = `${drawing}:${swipe}`;
  const existing = capabilityPromises.get(capabilityKey);
  if (existing) return existing;

  let drawingStylesheet = null;
  if (!controlPromise) {
    const controlStylesheet = loadStylesheet(documentRef, MAP_CONTROL_CSS);
    if (drawing) {
      drawingStylesheet = loadStylesheet(documentRef, DRAWING_CSS);
    }
    loadMapControl(documentRef, controlStylesheet);
  }

  const loading = Promise.all([
    loadMapControl(documentRef),
    ...(drawing ? [loadDrawing(documentRef, drawingStylesheet)] : []),
    ...(swipe ? [loadSwipe(documentRef)] : []),
  ]).catch((error) => {
    capabilityPromises.delete(capabilityKey);
    throw error;
  });
  capabilityPromises.set(capabilityKey, loading);
  return loading;
}

export function loadMapRoute(importRoute, loadMaps = loadAzureMaps) {
  return () =>
    Promise.all([loadMaps(), importRoute()]).then(([, route]) => route);
}

export function resetAzureMapsLoaderForTests() {
  controlPromise = null;
  drawingPromise = null;
  swipePromise = null;
  capabilityPromises.clear();
}