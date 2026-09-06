// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { PMTiles } from "pmtiles";
import { getPmtilesProtocol, InMemoryPMTilesSource } from "./pmtiles.js";

test("labeling and results share one protocol and archive cache", () => {
  const registrations = [];
  const atlas = { addProtocol: (...args) => registrations.push(args) };
  const labeling = getPmtilesProtocol(atlas);
  const results = getPmtilesProtocol(atlas);
  assert.equal(labeling, results);
  assert.equal(registrations.length, 1);
  assert.equal(registrations[0][0], "pmtiles");
  const archive = new PMTiles(new InMemoryPMTilesSource("/api/fixture", new ArrayBuffer(16)));
  labeling.add(archive);
  assert.equal(results.get("/api/fixture"), archive);
});

test("protocol registration waits for a usable SDK and can register a later SDK instance", () => {
  assert.throws(() => getPmtilesProtocol(null), /does not support/);
  const atlas = { addProtocol() {} };
  assert.ok(getPmtilesProtocol(atlas));
});

test("in-memory range reads preserve bytes and clamp the initial header read", async () => {
  const source = new InMemoryPMTilesSource("key", Uint8Array.from([1, 2, 3, 4]).buffer);
  assert.equal(source.getKey(), "key");
  assert.deepEqual(new Uint8Array((await source.getBytes(1, 2)).data), Uint8Array.from([2, 3]));
  assert.equal((await source.getBytes(0, 16384)).data.byteLength, 4);
});
