// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { attachPredictionEditing, normalizeSelectionBox } from "./predictionEditorMap.js";
import { downloadPrediction, predictionFilename } from "./predictionDownload.js";

function events() {
  const handlers = new Map();
  return {
    handlers,
    addEventListener(name, callback) {
      if (!handlers.has(name)) handlers.set(name, new Set());
      handlers.get(name).add(callback);
    },
    removeEventListener(name, callback) { handlers.get(name)?.delete(callback); },
    emit(name, value = {}) { for (const callback of handlers.get(name) || []) callback(value); },
  };
}
function gestureFixture() {
  const doc = { ...events(), defaultView: events() };
  const paints = [], resets = [], errors = [], queries = [];
  const box = { style: {} };
  const disposers = new Set();
  const panes = ["primary", "secondary"].map((key) => {
    const canvas = { ...events(), style: { cursor: "grab" }, getBoundingClientRect: () => ({ left: 10, top: 20 }) };
    const mapEvents = events();
    const settings = { dblClickZoomInteraction: key === "primary", dragPanInteraction: true, scrollZoomInteraction: true };
    const map = {
      settings, getCanvasContainer: () => canvas,
      getUserInteraction: () => ({ ...settings }),
      setUserInteraction: (changes) => Object.assign(settings, changes),
      events: {
        add: (name, _layer, callback) => mapEvents.addEventListener(name, callback),
        remove: (name, _layer, callback) => mapEvents.removeEventListener(name, callback),
      },
      positionsToPixels: () => [[5, 6]],
    };
    return { key, map, canvas, mapEvents, fillLayer: {} };
  });
  const renderer = {
    onDispose(callback) { disposers.add(callback); return () => disposers.delete(callback); },
    getPanes: () => panes,
    query: (key, bounds) => {
      queries.push([key, bounds]);
      return [{ id: 0 }, { id: 1 }, { id: 1 }];
    },
  };
  let enabled = true;
  const detach = attachPredictionEditing(renderer, {
    paint: (ids) => paints.push(ids), reset: (id) => resets.push(id),
    boxElement: box, onError: (error) => errors.push(error), documentObject: doc,
    canInteract: () => enabled,
  });
  return { doc, paints, resets, errors, box, panes, queries, detach, disposers, disable: () => { enabled = false; } };
}
const mouse = (x, y, extras = {}) => ({
  button: 0, clientX: x, clientY: y, ctrlKey: true,
  preventDefault() {}, stopPropagation() {}, ...extras,
});

test("click and model-reset callbacks work on both panes; mode restores original navigation settings", () => {
  const f = gestureFixture();
  for (const pane of f.panes) {
    assert.equal(pane.map.settings.dblClickZoomInteraction, false);
    assert.equal(pane.map.settings.dragPanInteraction, true);
    assert.equal(pane.map.settings.scrollZoomInteraction, true);
    pane.mapEvents.emit("click", { pixel: [5, 6], originalEvent: {} });
    pane.mapEvents.emit("contextmenu", { pixel: [5, 6], originalEvent: { preventDefault() {} } });
  }
  assert.deepEqual(f.paints, [[0], [0]]);
  assert.deepEqual(f.resets, [0, 0]);
  assert.deepEqual(f.queries.map(([key]) => key), ["primary", "primary", "secondary", "secondary"]);
  f.detach();
  assert.equal(f.panes[0].map.settings.dblClickZoomInteraction, true);
  assert.equal(f.panes[1].map.settings.dblClickZoomInteraction, false);
  for (const pane of f.panes) assert.equal(pane.canvas.style.cursor, "grab");
});

test("Ctrl+box on either pane paints a deduplicated batch and restores pan", () => {
  const f = gestureFixture();
  for (const pane of f.panes) {
    pane.canvas.emit("mousedown", mouse(20, 30));
    assert.equal(pane.map.settings.dragPanInteraction, false);
    f.doc.emit("mousemove", mouse(60, 80));
    assert.equal(f.box.style.display, "block");
    f.doc.emit("mouseup", mouse(60, 80));
    assert.equal(pane.map.settings.dragPanInteraction, true);
    assert.equal(f.box.style.display, "none");
  }
  assert.deepEqual(f.paints, [[0, 1], [0, 1]]);
  assert.deepEqual(f.queries[0][1], [[10, 10], [50, 60]]);
  f.detach();
});

test("cancel, blur, busy state and renderer disposal cannot strand drag-pan or apply a box", () => {
  for (const kind of ["escape", "blur", "busy", "dispose"]) {
    const f = gestureFixture();
    const pane = f.panes[0];
    pane.canvas.emit("mousedown", mouse(20, 30));
    if (kind === "escape") f.doc.emit("keydown", { key: "Escape" });
    if (kind === "blur") f.doc.defaultView.emit("blur");
    if (kind === "busy") { f.disable(); f.doc.emit("mousemove", mouse(40, 50)); }
    if (kind === "dispose") for (const cleanup of f.disposers) cleanup();
    assert.equal(pane.map.settings.dragPanInteraction, true, kind);
    f.doc.emit("mouseup", mouse(80, 90));
    assert.deepEqual(f.paints, [], kind);
    f.detach();
    assert.equal([...f.doc.handlers.values()].reduce((sum, value) => sum + value.size, 0), 0);
  }
});

test("ordinary dragging is not hijacked and tiny Ctrl boxes do not paint", () => {
  const f = gestureFixture();
  const pane = f.panes[0];
  pane.canvas.emit("mousedown", mouse(20, 30, { ctrlKey: false }));
  f.doc.emit("mouseup", mouse(80, 90, { ctrlKey: false }));
  assert.deepEqual(f.paints, []);
  pane.canvas.emit("mousedown", mouse(20, 30));
  f.doc.emit("mouseup", mouse(22, 32));
  assert.deepEqual(f.paints, []);
  assert.equal(normalizeSelectionBox({ x: 2, y: 2 }, { x: 3, y: 3 }), null);
  f.detach();
});

test("proxy downloads use server version filenames, with explicit raw/version fallbacks", () => {
  assert.equal(predictionFilename("attachment; filename=edited_v3.gpkg", 3), "edited_v3.gpkg");
  assert.equal(predictionFilename("attachment; filename*=UTF-8''version%204.gpkg", 4), "version 4.gpkg");
  assert.equal(predictionFilename("", 0), "predictions_raw.gpkg");
  assert.equal(predictionFilename("", 5), "predictions_v5.gpkg");
  assert.equal(predictionFilename('attachment; filename="../../v3.gpkg"', 3), "v3.gpkg");
});

test("download failure is visible and cannot trigger a bogus successful download", async () => {
  let clicked = false;
  await assert.rejects(downloadPrediction("/api/GetModelArtifact?version=99", 99, {
    fetchResponse: async () => Response.json({ error: "Unknown version" }, { status: 404 }),
    documentObject: { createElement: () => ({ click: () => { clicked = true; } }) },
  }), /Unknown version/);
  assert.equal(clicked, false);
});

test("a successful protected download uses the response filename and releases its blob", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const events = [];
  const link = { click() { events.push(["click", this.download, this.href]); }, remove() { events.push(["remove"]); } };
  const doc = { createElement: () => link, body: { appendChild() {} } };
  const urls = {
    createObjectURL: (blob) => { assert.equal(blob.size, 4); return "blob:fixture"; },
    revokeObjectURL: (url) => events.push(["revoke", url]),
  };
  await downloadPrediction("/api/GetModelArtifact?kind=gpkg&version=3", 3, {
    fetchResponse: async (url) => {
      assert.match(url, /kind=gpkg&version=3/);
      assert.equal(new URL(url, "https://haste.invalid").searchParams.has("_"), false);
      return new Response(new Uint8Array(4), { headers: { "content-disposition": 'attachment; filename="model_v3.gpkg"' } });
    },
    documentObject: doc, urls,
  });
  assert.deepEqual(events[0], ["click", "model_v3.gpkg", "blob:fixture"]);
  t.mock.timers.tick(1000);
  assert.deepEqual(events.at(-1), ["revoke", "blob:fixture"]);
});
