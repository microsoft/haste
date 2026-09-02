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

let loadPromise = null;

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

export function loadAzureMaps(documentRef = document) {
  if (loadPromise) return loadPromise;

  loadPromise = Promise.all([
    loadStylesheet(documentRef, MAP_CONTROL_CSS),
    loadStylesheet(documentRef, DRAWING_CSS),
    loadScript(documentRef, MAP_CONTROL_JS),
  ])
    .then(() =>
      Promise.all([
        loadScript(documentRef, DRAWING_JS),
        loadScript(documentRef, SWIPE_JS),
      ])
    )
    .catch((error) => {
      loadPromise = null;
      throw error;
    });
  return loadPromise;
}

export function loadMapRoute(importRoute, loadMaps = loadAzureMaps) {
  return () =>
    Promise.all([loadMaps(), importRoute()]).then(([, route]) => route);
}

export function resetAzureMapsLoaderForTests() {
  loadPromise = null;
}