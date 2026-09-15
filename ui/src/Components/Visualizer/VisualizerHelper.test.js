// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { getStudyAreaCameraOptions, whenVisualizerMapsReady } from "./VisualizerHelper.js";

const bounds = [-156.68695711093105, 20.872696441755018, -156.6621865203362, 20.888715560404812];

test("initial framing jumps to the supplied display extent without intermediate zoom requests", () => {
  const studyArea = Object.freeze([Object.freeze({ bbox: Object.freeze([...bounds]) })]);
  const options = getStudyAreaCameraOptions(studyArea, 0);
  assert.deepEqual(options, { bounds, type: "jump", duration: 0, padding: 100 });
  assert.notEqual(options.bounds, studyArea[0].bbox);
});

test("user Reset retains the existing animated camera framing and padding", () => {
  assert.deepEqual(getStudyAreaCameraOptions([{ bbox: bounds }]), {
    bounds, type: "fly", duration: 700, padding: 100,
  });
});

test("missing or malformed extents do not request a fabricated camera position", () => {
  for (const studyArea of [undefined, null, [], [{}], [{ bbox: null }], [{ bbox: [1, 2] }], [{ bbox: [1, 2, NaN, 4] }]]) {
    assert.equal(getStudyAreaCameraOptions(studyArea, 0), null);
  }
});

function mapFixture() {
  const readyHandlers = new Set();
  return {
    events: {
      add: (event, handler) => { assert.equal(event, "ready"); readyHandlers.add(handler); },
      remove: (event, handler) => { assert.equal(event, "ready"); readyHandlers.delete(handler); },
    },
    ready: () => readyHandlers.forEach((handler) => handler()),
    handlers: readyHandlers,
  };
}

test("both maps must be ready; either readiness order initializes once on the next layout frame", () => {
  for (const order of [[0, 1], [1, 0]]) {
    const maps = [mapFixture(), mapFixture()];
    const frames = [];
    let calls = 0;
    const dispose = whenVisualizerMapsReady(maps, () => calls++, (callback) => {
      frames.push(callback);
      return frames.length;
    }, () => {});
    maps[order[0]].ready();
    maps[order[0]].ready();
    assert.equal(frames.length, 0);
    maps[order[1]].ready();
    assert.equal(calls, 0);
    assert.equal(frames.length, 1);
    maps[order[1]].ready();
    frames[0]();
    maps[order[0]].ready();
    assert.equal(calls, 1);
    assert.equal(frames.length, 1);
    dispose();
    assert(maps.every((map) => map.handlers.size === 0));
  }
});

test("unmount before readiness removes listeners without initializing the maps", () => {
  const maps = [mapFixture(), mapFixture()];
  let scheduled = false;
  const dispose = whenVisualizerMapsReady(maps, () => assert.fail("Disposed view initialized"),
    () => { scheduled = true; }, () => {});
  maps[0].ready();
  dispose();
  maps[1].ready();
  assert.equal(scheduled, false);
  assert(maps.every((map) => map.handlers.size === 0));
});

test("unmount cancels queued layout work and guards an already queued callback", () => {
  const maps = [mapFixture(), mapFixture()];
  let frame;
  const cancelled = [];
  const dispose = whenVisualizerMapsReady(maps, () => assert.fail("Disposed view initialized"),
    (callback) => { frame = callback; return 42; }, (id) => cancelled.push(id));
  maps.forEach((map) => map.ready());
  dispose();
  assert.deepEqual(cancelled, [42]);
  frame();
});
