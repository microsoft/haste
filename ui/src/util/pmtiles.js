// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Adapted from PR136. Atlas has ONE handler per scheme; both screens must
// register archives in the same Protocol or one screen steals the other's reads.
import { FetchSource, PMTiles, Protocol } from "pmtiles";

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

export function footprintArchiveUrl(url) {
  const [path, query] = url.split("?");
  const params = new URLSearchParams(query);
  if (params.get("kind") !== "footprint_pmtiles" ||
      !params.has("projectId") || !params.has("imageLayerId")) return url;
  params.delete("modelId");
  params.sort();
  return `${path}?${params}`;
}

export class HttpPMTilesSource extends FetchSource {
  constructor(url, { signal, timeoutMs = 120000 } = {}) {
    super(url);
    this.initialSignal = signal;
    this.timeoutMs = timeoutMs;
  }

  async getBytes(offset, length, signal, etag) {
    const controller = new AbortController();
    const signals = [this.initialSignal, signal].filter(Boolean);
    const cancel = () => controller.abort(signals.find((item) => item.aborted)?.reason);
    for (const item of signals) {
      item.addEventListener("abort", cancel, { once: true });
      if (item.aborted) cancel();
    }
    const timer = setTimeout(() => controller.abort(
      new Error("PMTiles range request timed out.")
    ), this.timeoutMs);
    try {
      controller.signal.throwIfAborted();
      const result = await super.getBytes(offset, length, controller.signal, etag);
      controller.signal.throwIfAborted();
      return result;
    } finally {
      clearTimeout(timer);
      for (const item of signals) item.removeEventListener("abort", cancel);
      controller.abort();
    }
  }
}

export async function loadFootprintArchive(url, signal) {
  signal?.throwIfAborted();
  const archiveKey = footprintArchiveUrl(url);
  const protocol = getPmtilesProtocol();
  let archive = protocol.get(archiveKey);
  if (archive) {
    const header = await archive.getHeader();
    signal?.throwIfAborted();
    return { archiveKey, header };
  }

  const source = new HttpPMTilesSource(archiveKey, { signal });
  archive = new PMTiles(source);
  try {
    const header = await archive.getHeader();
    signal?.throwIfAborted();
    protocol.add(archive);
    return { archiveKey, header };
  } finally {
    // Only the first header read belongs to this caller. Cached archives
    // outlive routes; subsequent tile reads use the renderer's own signal.
    source.initialSignal = undefined;
  }
}
