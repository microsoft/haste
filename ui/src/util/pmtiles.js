// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Shared PMTiles plumbing for the Azure Maps screens.
//
// `atlas.addProtocol("pmtiles", fn)` keeps exactly ONE handler per scheme:
// the last registration wins. Each `new Protocol()` owns its own archive
// cache, so if two screens each registered their own instance, whichever
// registered last would serve every tile request — including requests for
// archives the *other* instance had added, which it cannot resolve (it falls
// back to a range-request FetchSource that the SWA /api proxy does not
// support). Both the Interactive Labeler and the Prediction Editor therefore
// share the single instance handed out here.

import { Protocol } from "pmtiles";

let protocolInstance = null;
let isRegistered = false;

/**
 * The process-wide pmtiles Protocol, registering the "pmtiles" scheme with
 * Azure Maps the first time the SDK is available. Returns null when there is
 * no window (SSR / unit tests).
 *
 * Callers add their archive with `protocol.add(new PMTiles(source))` and then
 * point a VectorTileSource at `pmtiles://<key>`, where <key> is the same
 * string the source's `getKey()` returns.
 */
export function getPmtilesProtocol() {
  if (typeof window === "undefined") return null;
  if (!protocolInstance) {
    protocolInstance = new Protocol();
  }
  if (
    !isRegistered &&
    window.atlas &&
    typeof window.atlas.addProtocol === "function"
  ) {
    // The bound `.tile` member is what addProtocol expects.
    window.atlas.addProtocol("pmtiles", protocolInstance.tile);
    isRegistered = true;
  }
  return protocolInstance;
}

/**
 * pmtiles.js reads an archive through a `Source` (getKey + getBytes). Its
 * default FetchSource issues HTTP Range requests, but these screens are
 * served behind an Azure Static Web App whose /api proxy does NOT honor byte
 * serving: a ranged GET comes back as a full 200, so pmtiles throws "Server
 * returned no content-length header or content-length exceeding request."
 * Downloading the whole archive once and satisfying every range read from
 * that in-memory buffer sidesteps the problem.
 *
 * `getKey()` must equal the string used in the `pmtiles://<key>` source URL
 * so Protocol.add()'s lookup matches.
 */
export class InMemoryPMTilesSource {
  constructor(key, arrayBuffer) {
    this._key = key;
    this._buf = arrayBuffer;
  }
  getKey() {
    return this._key;
  }
  async getBytes(offset, length) {
    // ArrayBuffer.slice clamps to the buffer end, which is what pmtiles
    // expects for the initial 16 KB header read on a smaller archive.
    return { data: this._buf.slice(offset, offset + length) };
  }
}

/**
 * Download an entire artifact through the same-origin API proxy as raw bytes.
 * Used for the PMTiles archive so it can be read fully in memory (see
 * InMemoryPMTilesSource) rather than via unsupported range requests.
 */
export async function fetchArtifactBuffer(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `Failed to fetch PMTiles archive (HTTP ${response.status}).`
    );
  }
  return response.arrayBuffer();
}
