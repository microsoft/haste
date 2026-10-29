// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export const TILE_CREDENTIAL_REFRESH_BUFFER_MS = 5 * 60 * 1000;
export const TILE_CREDENTIAL_FALLBACK_REFRESH_MS = 45 * 60 * 1000;
export const TILE_CREDENTIAL_VISIBILITY_WINDOW_MS = 60 * 1000;
export const TILE_CREDENTIAL_RETRY_MS = 60 * 1000;

export function getTileCredentialRefreshAt(
  tileCredentialExpiresAt,
  now = Date.now()
) {
  const expiresAt = Date.parse(tileCredentialExpiresAt);
  if (Number.isFinite(expiresAt)) {
    return expiresAt - TILE_CREDENTIAL_REFRESH_BUFFER_MS;
  }
  return now + TILE_CREDENTIAL_FALLBACK_REFRESH_MS;
}

export function getTileCredentialRefreshDelay(
  tileCredentialExpiresAt,
  now = Date.now()
) {
  return Math.max(
    0,
    getTileCredentialRefreshAt(tileCredentialExpiresAt, now) - now
  );
}

export function shouldRefreshCredentialsOnVisibility(
  refreshAt,
  now = Date.now()
) {
  return (
    Number.isFinite(refreshAt) &&
    now + TILE_CREDENTIAL_VISIBILITY_WINDOW_MS >= refreshAt
  );
}

// Pre-event imagery is optional, so a missing URL is an empty one.
function requireImageryUrls(nextData) {
  const imagery = nextData?.imagery;
  if (!imagery || typeof imagery !== "object") {
    throw new Error("The imagery credential response is incomplete.");
  }
  return {
    preEventTileUrl: imagery.preEventTileUrl || "",
    postEventTileUrl: imagery.postEventTileUrl || "",
  };
}

function transformTileUrl(transform, tileUrl) {
  const transformed = transform ? transform(tileUrl) : tileUrl;
  if (typeof transformed !== "string" || (tileUrl && !transformed)) {
    throw new Error("The imagery credential response contains an invalid URL.");
  }
  return transformed;
}

/**
 * Updates only credential-bearing imagery fields and existing TileLayers.
 * Labels, validation selections, and other in-memory data remain untouched.
 */
export function applyTileCredentialUpdate({
  dataRef,
  nextData,
  layerBindings = [],
  onApplied,
}) {
  if (!dataRef) {
    throw new Error("An imagery data reference is required.");
  }

  const nextImagery = requireImageryUrls(nextData);
  const previousData = dataRef.current || {};
  const previousImagery = previousData.imagery || {};
  const mergedData = {
    ...previousData,
    imagery: {
      ...previousImagery,
      preEventTileUrl: nextImagery.preEventTileUrl,
      postEventTileUrl: nextImagery.postEventTileUrl,
    },
  };

  if (
    Object.prototype.hasOwnProperty.call(nextData, "tileCredentialExpiresAt")
  ) {
    mergedData.tileCredentialExpiresAt = nextData.tileCredentialExpiresAt;
  } else {
    delete mergedData.tileCredentialExpiresAt;
  }

  const updatedLayers = [];
  try {
    for (const binding of layerBindings) {
      const imageryKey = binding.imageryKey;
      const layer = binding.layerRef?.current;
      if (!layer || typeof layer.setOptions !== "function") continue;

      const nextUrl = transformTileUrl(
        binding.transformTileUrl,
        nextImagery[imageryKey]
      );
      const previousUrl = transformTileUrl(
        binding.transformTileUrl,
        previousImagery[imageryKey] || ""
      );

      // Record before calling setOptions so a layer that mutates and then
      // throws can still be rolled back.
      updatedLayers.push({ layer, previousUrl });
      layer.setOptions({ tileUrl: nextUrl });
    }

    dataRef.current = mergedData;
    onApplied?.(mergedData);
    return mergedData;
  } catch (error) {
    dataRef.current = previousData;
    for (let index = updatedLayers.length - 1; index >= 0; index -= 1) {
      try {
        const { layer, previousUrl } = updatedLayers[index];
        layer.setOptions({ tileUrl: previousUrl });
      } catch {
        // Preserve the original refresh error; rollback is best-effort.
      }
    }
    throw error;
  }
}

export function createTileCredentialRefreshController({
  fetchCredentials,
  applyCredentials,
  onError = () => {},
  onSuccess = () => {},
  now = Date.now,
  setTimer = (callback, delay) => globalThis.setTimeout(callback, delay),
  clearTimer = (timerId) => globalThis.clearTimeout(timerId),
  documentTarget = globalThis.document,
}) {
  let disposed = false;
  let listening = false;
  let timerId = null;
  let refreshAt = null;
  let refreshPromise = null;

  function clearScheduledRefresh() {
    if (timerId !== null) {
      clearTimer(timerId);
      timerId = null;
    }
  }

  function schedule(data) {
    if (disposed) return;
    clearScheduledRefresh();
    refreshAt = getTileCredentialRefreshAt(
      data?.tileCredentialExpiresAt,
      now()
    );
    const delay = Math.max(0, refreshAt - now());
    timerId = setTimer(() => {
      timerId = null;
      return refresh();
    }, delay);
  }

  function scheduleRetry() {
    if (disposed) return;
    clearScheduledRefresh();
    timerId = setTimer(() => {
      timerId = null;
      return refresh();
    }, TILE_CREDENTIAL_RETRY_MS);
  }

  function refresh() {
    if (disposed) return Promise.resolve(false);
    if (refreshPromise) return refreshPromise;

    refreshPromise = (async () => {
      try {
        const nextData = await fetchCredentials();
        if (disposed) return false;
        await applyCredentials(nextData);
        if (disposed) return false;
        onSuccess();
        schedule(nextData);
        return true;
      } catch {
        if (!disposed) {
          onError();
          scheduleRetry();
        }
        return false;
      } finally {
        refreshPromise = null;
      }
    })();

    return refreshPromise;
  }

  function handleVisibilityChange() {
    if (
      documentTarget?.visibilityState === "visible" &&
      shouldRefreshCredentialsOnVisibility(refreshAt, now())
    ) {
      return refresh();
    }
    return undefined;
  }

  function start(initialData) {
    if (disposed || !initialData) return;
    if (!listening && documentTarget?.addEventListener) {
      documentTarget.addEventListener(
        "visibilitychange",
        handleVisibilityChange
      );
      listening = true;
    }
    schedule(initialData);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    clearScheduledRefresh();
    if (listening && documentTarget?.removeEventListener) {
      documentTarget.removeEventListener(
        "visibilitychange",
        handleVisibilityChange
      );
    }
    listening = false;
  }

  return {
    start,
    refresh,
    dispose,
  };
}
