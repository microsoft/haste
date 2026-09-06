// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import {
  createPredictionRenderer, discoverVectorSourceId, FALLBACK_COLORS,
  fillColorExpression, findGlMap, resolveMapColors,
} from "./predictionFootprintMap.js";

const attrs = {
  n: 2, ids: [0, 1], overtureIds: ["a", "b"], classes: ["Damaged", "Unknown"],
};

function fixture(t, { secondaryLoaded = true, features = [0, 1] } = {}) {
  const oldFrame = globalThis.requestAnimationFrame;
  const oldCancel = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
  globalThis.cancelAnimationFrame = clearTimeout;
  t.after(() => {
    if (oldFrame) globalThis.requestAnimationFrame = oldFrame;
    else delete globalThis.requestAnimationFrame;
    if (oldCancel) globalThis.cancelAnimationFrame = oldCancel;
    else delete globalThis.cancelAnimationFrame;
  });
  const operations = [];
  const errors = [];
  class Source {
    constructor(id, options) { this.id = id; this.options = options; }
  }
  class Layer {
    constructor(source, id, options) {
      this.source = source;
      this.id = id;
      this.options = options;
    }
    setOptions(options) {
      Object.assign(this.options, options);
      operations.push(["options", this.id, options]);
    }
  }
  class PolygonLayer extends Layer {}
  const atlas = {
    source: { VectorTileSource: Source },
    layer: { PolygonLayer, LineLayer: Layer },
  };
  const maps = [0, 1].map((number) => {
    const style = {
      sources: {
        basemapBuildings: { type: "vector" },
        unrelatedPredictions: { type: "vector" },
      },
      layers: [
        { id: "baseBuildings", source: "basemapBuildings", "source-layer": "buildings", type: "fill" },
      ],
    };
    const handlers = new Map();
    let currentSource;
    const gl = {
      loaded: number === 0 || secondaryLoaded,
      features,
      getStyle: () => style,
      on(event, fn) {
        if (!handlers.has(event)) handlers.set(event, new Set());
        handlers.get(event).add(fn);
      },
      off(event, fn) { handlers.get(event)?.delete(fn); },
      emit(event, value = {}) { for (const fn of handlers.get(event) || []) fn(value); },
      isSourceLoaded: () => gl.loaded,
      queryRenderedFeatures(_box, options) {
        assert.ok(options.layers.length > 0);
        assert.ok(options.layers.every((id) => id !== "baseBuildings"));
        return gl.features.map((id) => ({
          id, source: currentSource, properties: { overture_id: attrs.overtureIds[id] },
        }));
      },
      setFeatureState(target, state) { operations.push(["state", number, target, state]); },
      removeFeatureState(target) { operations.push(["clear", number, target]); },
    };
    return {
      map: gl,
      handlers,
      sources: {
        add(source) {
          // Deliberately renamed, to exercise the real Atlas naming boundary.
          currentSource = `atlas-${source.id}`;
          style.sources[currentSource] = { type: "vector", url: source.options.url };
        },
        remove() {
          operations.push(["removeSource", number]);
          delete style.sources[currentSource];
        },
      },
      layers: {
        add(layer) {
          style.layers.push({
            id: `atlas-${layer.id}`, source: currentSource,
            type: layer instanceof PolygonLayer ? "fill" : "line",
            "source-layer": layer.options.sourceLayer,
          });
        },
        remove(layer) {
          operations.push(["removeLayer", number, layer.id]);
          style.layers = style.layers.filter((item) => item.id !== `atlas-${layer.id}`);
        },
      },
    };
  });
  const create = (nextAttrs = attrs) => {
    const renderer = createPredictionRenderer({
      atlas, maps, attrs: nextAttrs, archiveKey: "/api/tiles", onError: (error) => errors.push(error),
    });
    t.after(() => renderer.dispose());
    return renderer;
  };
  return { atlas, maps, create, operations, errors };
}

test("both renderers receive identical classes on their own discovered sources", async (t) => {
  const { create, operations, maps } = fixture(t);
  const renderer = create();
  await renderer.ready;
  const state = operations.filter(([op]) => op === "state");
  assert.equal(state.length, 4);
  for (const id of [0, 1]) {
    const writes = state.filter((entry) => entry[2].id === id);
    assert.equal(writes.length, 2);
    assert.deepEqual(writes[0][3], writes[1][3]);
    assert.notEqual(writes[0][2].source, writes[1][2].source);
    assert.equal(writes[0][2].sourceLayer, "buildings");
  }
  assert.equal(state.find((entry) => entry[2].id === 1)[3].cls, 3);
  for (const map of maps) assert.deepEqual([...map.handlers.keys()].sort(), ["error", "idle", "moveend", "sourcedata"]);
});

test("one loaded pane cannot advertise two-pane readiness", async (t) => {
  const { create, maps } = fixture(t, { secondaryLoaded: false });
  const renderer = create();
  let ready = false;
  renderer.ready.then(() => { ready = true; });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(ready, false);
  maps[1].map.loaded = true;
  maps[1].map.emit("sourcedata");
  await renderer.ready;
  assert.equal(ready, true);
});

test("source discovery excludes preexisting basemap and unrelated prediction sources", () => {
  const previous = new Set(["basemapBuildings", "unrelatedPredictions"]);
  const gl = { getStyle: () => ({
    sources: {
      basemapBuildings: { type: "vector" }, unrelatedPredictions: { type: "vector" },
      renamedSource: { type: "vector", url: "pmtiles://ours" },
      newlyLoadedBasemap: { type: "vector" },
    },
  }) };
  assert.equal(discoverVectorSourceId(gl, previous, "ours", "pmtiles://ours"), "renamedSource");
  assert.equal(discoverVectorSourceId(gl, new Set([...previous, "renamedSource"]), "ours", "pmtiles://ours"), null);
});

test("missing secondary renderer surfaces an error and removes partial primary layers", async (t) => {
  const { create, maps, operations, errors } = fixture(t);
  maps[1].map = null;
  const renderer = create();
  await assert.rejects(renderer.ready, /Secondary map has no usable/);
  assert.match(errors[0].message, /Secondary/);
  assert.ok(operations.some(([op]) => op === "removeSource"));
});

test("native tile errors fail the renderer instead of leaving a ready grey map", async (t) => {
  const { create, maps, errors, operations } = fixture(t);
  const renderer = create();
  await renderer.ready;
  maps[1].map.emit("error", { error: new Error("PMTiles decode failure") });
  assert.match(errors[0].message, /PMTiles decode failure/);
  assert.equal(operations.filter(([op]) => op === "removeSource").length, 2);
});

test("feature-state failures and mismatched source IDs surface visible errors", async (t) => {
  const { create, maps, errors } = fixture(t);
  maps[0].map.setFeatureState = () => { throw new Error("renderer rejected feature-state"); };
  await assert.rejects(create().ready, /rejected feature-state/);
  assert.match(errors[0].message, /feature-state/);
});

test("unknown footprint row IDs are rejected rather than painted with fallback classes", async (t) => {
  const { create } = fixture(t, { features: [99] });
  await assert.rejects(create().ready, /row IDs do not match/);
});

test("both panes clear state before removing layers/sources and detach listeners", async (t) => {
  const { create, operations, maps } = fixture(t);
  const renderer = create();
  await renderer.ready;
  renderer.dispose();
  for (const pane of [0, 1]) {
    const clear = operations.findIndex(([op, number]) => op === "clear" && number === pane);
    const remove = operations.findIndex(([op, number]) => op === "removeSource" && number === pane);
    assert.ok(clear >= 0 && clear < remove);
    assert.equal([...maps[pane].handlers.values()].flatMap((handlers) => [...handlers]).length, 0);
  }
});

test("replacing predictions rebuilds both sources without retaining the previous classes", async (t) => {
  const { create, operations } = fixture(t);
  const first = create();
  await first.ready;
  first.dispose();
  const boundary = operations.length;
  const second = create({ ...attrs, classes: ["NotDamaged", "Damaged"] });
  await second.ready;
  const states = operations.slice(boundary).filter(([op]) => op === "state");
  assert.equal(states.length, 4);
  assert.equal(states.find((entry) => entry[2].id === 0)[3].cls, 2);
  assert.equal(states.find((entry) => entry[2].id === 1)[3].cls, 1);
});

test("theme colors and visibility are updated on both panes without rebuilding data", async (t) => {
  const { create, operations } = fixture(t);
  const renderer = create();
  await renderer.ready;
  const colors = { ...FALLBACK_COLORS, damaged: "red", outline: "white" };
  renderer.setColors(colors);
  renderer.setVisible(false);
  assert.equal(operations.filter(([op, , options]) => op === "options" && options.visible === false).length, 4);
  assert.equal(operations.filter(([op, , options]) => op === "options" && options.fillColor?.includes("red")).length, 2);
});

test("theme lookup produces parseable colors, and renderer access is duck-typed", () => {
  assert.equal(resolveMapColors({ damaged: "var(--danger)" }, () => " red ").damaged, "red");
  assert.equal(resolveMapColors({}, () => "").unknown, FALLBACK_COLORS.unknown);
  assert.ok(JSON.stringify(fillColorExpression()).includes("feature-state"));
  const gl = { setFeatureState() {} };
  assert.equal(findGlMap({ _map: gl }), gl);
  assert.equal(findGlMap({}), null);
});
