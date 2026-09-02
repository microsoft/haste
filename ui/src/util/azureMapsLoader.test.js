import test from "node:test";
import assert from "node:assert/strict";

import {
  loadAzureMaps,
  loadMapRoute,
  resetAzureMapsLoaderForTests,
} from "./azureMapsLoader.js";

function fakeDocument({ failOnce = null, autoLoad = true } = {}) {
  const elements = [];
  const attempts = new Map();

  function asset(element) {
    return element.src || element.href;
  }

  const documentRef = {
    elements,
    head: {
      appendChild(element) {
        elements.push(element);
        const name = asset(element);
        attempts.set(name, (attempts.get(name) || 0) + 1);
        if (autoLoad) {
          queueMicrotask(() => {
            const event = name === failOnce && attempts.get(name) === 1
              ? "error"
              : "load";
            element.listeners.get(event)?.();
          });
        }
      },
    },
    createElement(tagName) {
      return {
        tagName,
        dataset: {},
        listeners: new Map(),
        addEventListener(name, callback) {
          this.listeners.set(name, callback);
        },
        remove() {
          const index = elements.indexOf(this);
          if (index >= 0) elements.splice(index, 1);
        },
      };
    },
    querySelector(selector) {
      const match = selector.match(/data-azure-maps-(?:src|href)="(.+)"/);
      return elements.find((element) => asset(element) === match?.[1]) || null;
    },
    dispatchAsset(name, event = "load") {
      const element = elements.find((candidate) => asset(candidate) === name);
      element?.listeners.get(event)?.();
    },
  };
  return documentRef;
}

test.beforeEach(() => resetAzureMapsLoaderForTests());

test("loads styles, map control, drawing tools, and swipe in order", async () => {
  const documentRef = fakeDocument();

  await loadAzureMaps(documentRef);

  assert.deepEqual(
    documentRef.elements.map((element) => element.src || element.href),
    [
      "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css",
      "https://atlas.microsoft.com/sdk/javascript/drawing/1/atlas-drawing.min.css",
      "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.js",
      "https://atlas.microsoft.com/sdk/javascript/drawing/1/atlas-drawing.min.js",
      "/assets/js/azure-maps-swipe-map.min.js",
    ]
  );
});

test("loads independent map assets in two concurrent phases", async () => {
  const documentRef = fakeDocument({ autoLoad: false });
  const initialAssets = [
    "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css",
    "https://atlas.microsoft.com/sdk/javascript/drawing/1/atlas-drawing.min.css",
    "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.js",
  ];
  const dependentAssets = [
    "https://atlas.microsoft.com/sdk/javascript/drawing/1/atlas-drawing.min.js",
    "/assets/js/azure-maps-swipe-map.min.js",
  ];

  const loading = loadAzureMaps(documentRef);
  assert.deepEqual(
    documentRef.elements.map((element) => element.src || element.href),
    initialAssets
  );

  initialAssets.forEach((asset) => documentRef.dispatchAsset(asset));
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(
    documentRef.elements.map((element) => element.src || element.href),
    [...initialAssets, ...dependentAssets]
  );

  dependentAssets.forEach((asset) => documentRef.dispatchAsset(asset));
  await loading;
});

test("starts the route import while Azure Maps is loading", async () => {
  let resolveMaps;
  let resolveRoute;
  const calls = [];
  const loadMaps = () => {
    calls.push("maps");
    return new Promise((resolve) => {
      resolveMaps = resolve;
    });
  };
  const importRoute = () => {
    calls.push("route");
    return new Promise((resolve) => {
      resolveRoute = resolve;
    });
  };
  const routeModule = { default: "route" };

  const loading = loadMapRoute(importRoute, loadMaps)();
  assert.deepEqual(calls, ["maps", "route"]);
  resolveRoute(routeModule);
  resolveMaps();

  assert.equal(await loading, routeModule);
});

test("deduplicates concurrent and completed loads", async () => {
  const documentRef = fakeDocument();

  const first = loadAzureMaps(documentRef);
  const second = loadAzureMaps(documentRef);
  assert.equal(first, second);
  await first;
  await loadAzureMaps(documentRef);

  assert.equal(documentRef.elements.length, 5);
});

test("reuses an existing loaded asset", async () => {
  const documentRef = fakeDocument();
  const existing = documentRef.createElement("link");
  existing.href =
    "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css";
  existing.dataset.azureMapsHref = existing.href;
  existing.dataset.loaded = "true";
  documentRef.elements.push(existing);

  await loadAzureMaps(documentRef);

  assert.equal(
    documentRef.elements.filter((element) => element.href === existing.href)
      .length,
    1
  );
});

test("waits for an existing asset that is still loading", async () => {
  const documentRef = fakeDocument();
  const existing = documentRef.createElement("link");
  existing.href =
    "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css";
  existing.dataset.azureMapsHref = existing.href;
  documentRef.elements.push(existing);

  const loading = loadAzureMaps(documentRef);
  queueMicrotask(() => existing.listeners.get("load")?.());
  await loading;

  assert.equal(
    documentRef.elements.filter((element) => element.href === existing.href)
      .length,
    1
  );
});

test("removes a failed asset and allows retry", async () => {
  const failedAsset =
    "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.js";
  const documentRef = fakeDocument({ failOnce: failedAsset });

  await assert.rejects(loadAzureMaps(documentRef), /Unable to load/);
  assert.equal(
    documentRef.elements.some((element) => element.src === failedAsset),
    false
  );

  await loadAzureMaps(documentRef);
  assert.equal(
    documentRef.elements.filter((element) => element.src === failedAsset).length,
    1
  );
});

test("reports a failed stylesheet URL", async () => {
  const failedAsset =
    "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css";
  const documentRef = fakeDocument({ failOnce: failedAsset });

  await assert.rejects(loadAzureMaps(documentRef), (error) => {
    assert.equal(
      error.message,
      `Unable to load Azure Maps asset: ${failedAsset}`
    );
    return true;
  });
});

test("uses the global document by default", async () => {
  const documentRef = fakeDocument();
  globalThis.document = documentRef;

  try {
    await loadAzureMaps();
  } finally {
    delete globalThis.document;
  }

  assert.equal(documentRef.elements.length, 5);
});