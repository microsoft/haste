import test from "node:test";
import assert from "node:assert/strict";

import {
  loadAzureMaps,
  resetAzureMapsLoaderForTests,
} from "./azureMapsLoader.js";

function fakeDocument({ failOnce = null } = {}) {
  const elements = [];
  const attempts = new Map();

  function asset(element) {
    return element.src || element.href;
  }

  return {
    elements,
    head: {
      appendChild(element) {
        elements.push(element);
        const name = asset(element);
        attempts.set(name, (attempts.get(name) || 0) + 1);
        queueMicrotask(() => {
          const event = name === failOnce && attempts.get(name) === 1
            ? "error"
            : "load";
          element.listeners.get(event)?.();
        });
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
  };
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

  await assert.rejects(loadAzureMaps(documentRef), new RegExp(failedAsset));
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