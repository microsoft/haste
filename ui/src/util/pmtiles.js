// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Adapted from PR136. Atlas has ONE handler per scheme; both screens must
// register archives in the same Protocol or one screen steals the other's reads.
import { Protocol } from "pmtiles";

let protocolInstance;
const registered = new WeakSet();

export function getPmtilesProtocol(atlas = globalThis.window?.atlas) {
  if (!atlas || typeof atlas.addProtocol !== "function") {
    throw new Error("Azure Maps does not support the PMTiles protocol.");
  }
  protocolInstance ??= new Protocol();
  if (!registered.has(atlas)) {
    atlas.addProtocol("pmtiles", protocolInstance.tile);
    registered.add(atlas);
  }
  return protocolInstance;
}

// SWA's API proxy does not reliably honor ranges. Fetch a bounded archive
// once, then satisfy pmtiles' byte reads from memory.
export class InMemoryPMTilesSource {
  constructor(key, buffer) {
    this.key = key;
    this.buffer = buffer;
  }
  getKey() { return this.key; }
  async getBytes(offset, length) {
    return { data: this.buffer.slice(offset, offset + length) };
  }
}
