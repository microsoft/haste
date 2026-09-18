// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Adapted from PR136. Atlas has ONE handler per scheme; both screens must
// register archives in the same Protocol or one screen steals the other's reads.
import { EtagMismatch, FetchSource, PMTiles, Protocol } from "pmtiles";
import { readResponseBuffer } from "../Components/InteractiveLabeler/interactiveLabelerLoading.js";

// Bound each directory/metadata/tile read, not the size of a streamed archive.
export const MAX_PMTILES_RANGE_BYTES = 64 * 1024 * 1024;

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

// The shared HTTP source/cache lifecycle comes from #201 (51d1ab8).
// FetchSource supplies the URL, custom headers and browser cache policy. Its
// default reader also accepts small HTTP 200 responses and unbounded bodies;
// our protected endpoint must return a bounded 206 for EVERY archive read.
export class HttpPMTilesSource extends FetchSource {
  constructor(url, { signal, timeoutMs = 120000 } = {}) {
    super(url);
    this.initialSignal = signal;
    this.timeoutMs = timeoutMs;
  }

  async getBytes(offset, length, signal, etag) {
    if (!Number.isSafeInteger(offset) || offset < 0 ||
        !Number.isSafeInteger(length) || length <= 0 ||
        length > MAX_PMTILES_RANGE_BYTES || !Number.isSafeInteger(offset + length)) {
      throw new Error("Invalid or oversized PMTiles byte range.");
    }
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
      const headers = new Headers(this.customHeaders);
      headers.set("Range", `bytes=${offset}-${offset + length - 1}`);
      const options = {
        signal: controller.signal, headers, credentials: this.credentials,
        cache: this.mustReload ? "reload" : this.chromeWindowsNoCache ? "no-store" : undefined,
      };
      let response = await fetch(this.url, options);
      // Preserve FetchSource's short-archive retry, but never let a malformed
      // 416 expand the requested range into a full/unbounded archive download.
      if (offset === 0 && response.status === 416) {
        const match = /^bytes \*\/(\d+)$/.exec(response.headers.get("Content-Range") || "");
        const actualLength = Number(match?.[1]);
        if (!Number.isSafeInteger(actualLength) || actualLength <= 0 || actualLength >= length) {
          throw new Error("Invalid PMTiles short-archive range response.");
        }
        await response.body?.cancel();
        length = actualLength;
        headers.set("Range", `bytes=0-${actualLength - 1}`);
        response = await fetch(this.url, { ...options, cache: "reload" });
      }
      let newEtag = response.headers.get("ETag");
      if (newEtag?.startsWith("W/")) newEtag = null;
      if (response.status === 416 || (etag && newEtag && newEtag !== etag)) {
        this.mustReload = true;
        throw new EtagMismatch(`Server returned non-matching ETag ${etag}.`);
      }
      if (response.status !== 206) {
        const error = new Error(response.status === 200
          ? "PMTiles requires HTTP 206 Byte Serving; full archive responses are not supported."
          : `Bad response code: ${response.status}`);
        error.status = response.status;
        throw error;
      }
      const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get("Content-Range") || "");
      const [start, end, total] = range ? range.slice(1).map(Number) : [];
      if (![start, end, total].every(Number.isSafeInteger) || start !== offset ||
          end < start || end !== Math.min(offset + length, total) - 1) {
        throw new Error("Invalid PMTiles Content-Range response.");
      }
      const data = await readResponseBuffer(response, undefined, {
        signal: controller.signal, maxBytes: end - start + 1,
      });
      controller.signal.throwIfAborted();
      if (data.byteLength !== end - start + 1) {
        throw new Error("Incomplete PMTiles range response.");
      }
      return {
        data, etag: newEtag || undefined,
        cacheControl: response.headers.get("Cache-Control") || undefined,
        expires: response.headers.get("Expires") || undefined,
      };
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
    // Only initialization belongs to this caller. Cached archives outlive
    // routes; subsequent tile reads use the renderer's own signal.
    source.initialSignal = undefined;
  }
}
