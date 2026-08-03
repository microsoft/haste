// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);
const STORAGE_PROXY_PATHS = new Set([
  "/api/haste/storage/get-artifacts",
  "/api/haste/storage/get-project-artifacts",
]);

function parseHttpUrl(value, base) {
  if (typeof value !== "string" || !value) return null;
  try {
    const parsed = new URL(value, base);
    if (!["http:", "https:"].includes(parsed.protocol)) return null;
    if (parsed.username || parsed.password) return null;
    return parsed;
  } catch {
    return null;
  }
}

function isAllowedStorageSource(parsed, browserHostname) {
  if (parsed.protocol === "https:" && parsed.hostname.endsWith(".blob.core.windows.net")) {
    return true;
  }
  if (parsed.protocol === "http:" && parsed.hostname === "azurite") {
    return true;
  }
  return (
    parsed.protocol === "http:" &&
    LOCAL_HOSTS.has(browserHostname) &&
    LOCAL_HOSTS.has(parsed.hostname)
  );
}

function storagePathSegments(parsed) {
  const segments = parsed.pathname.split("/").filter(Boolean);
  try {
    return segments.every((segment) => {
      const decoded = decodeURIComponent(segment);
      return ![".", ".."].includes(decoded) && !/[\\/]/.test(decoded);
    })
      ? segments
      : null;
  } catch {
    return null;
  }
}

export function buildBrowserStorageUrl(url, storageProxy, browserUrl) {
  const browser = parseHttpUrl(browserUrl);
  const source = parseHttpUrl(url);
  if (!browser || !source) return null;
  if (!isAllowedStorageSource(source, browser.hostname)) return null;
  const sourceSegments = storagePathSegments(source);
  if (!sourceSegments || sourceSegments.length < 2) return null;

  if (!storageProxy) {
    if (source.hostname !== "azurite") {
      return source.toString();
    }
    source.hostname = browser.hostname;
    return source.toString();
  }

  const target = parseHttpUrl(storageProxy, browser.origin);
  if (!target) return null;
  const targetPath = target.pathname.replace(/\/+$/, "");
  const isManagedIdentityProxy = STORAGE_PROXY_PATHS.has(targetPath);
  const isLocalStorage =
    target.hostname === browser.hostname ||
    (LOCAL_HOSTS.has(browser.hostname) && LOCAL_HOSTS.has(target.hostname));
  if (!isManagedIdentityProxy && !isLocalStorage) return null;
  const expectedSegments = targetPath.endsWith("/get-project-artifacts") ? 3 : 4;
  if (isManagedIdentityProxy && sourceSegments.length !== expectedSegments) {
    return null;
  }

  target.pathname = `${targetPath}/${source.pathname.replace(/^\/+/, "")}`;
  target.hash = "";
  if (isManagedIdentityProxy) {
    target.search = "";
  } else {
    target.search = source.search;
  }
  return target.toString();
}

export function toBrowserBlobUrl(url) {
  if (typeof window === "undefined") return null;
  return buildBrowserStorageUrl(url, null, window.location.href);
}

export function toBrowserStorageUrl(url) {
  if (typeof window === "undefined") return null;
  return buildBrowserStorageUrl(
    url,
    import.meta.env?.VITE_STORAGE_APIM_URL,
    window.location.href
  );
}

// Interactive Labeler imagery tiles are served by titiler. Tile-URL templates
// are persisted with the deployment-relative `/api/titiler/<path>` prefix,
// which in the cloud is routed by APIM (and in docker by the nginx api-proxy).
// Running the UI locally via `swa start` there is no such route, so imagery
// 404s. When VITE_TITILER_URL is set AND the UI is on localhost, rewrite that
// prefix to a directly-reachable titiler base. No-op in production (non-local
// host) and when the env var is unset, so it's safe to ship.
export function toBrowserTitilerUrl(url) {
  if (typeof window === "undefined") return "";
  const source = parseHttpUrl(url, window.location.origin);
  if (!source) return "";
  if (!LOCAL_HOSTS.has(window.location.hostname)) return url;
  const base = import.meta.env?.VITE_TITILER_URL;
  if (!base) return url;
  const marker = "/api/titiler/";
  if (!source.pathname.startsWith(marker)) return "";
  const target = parseHttpUrl(base, window.location.origin);
  if (!target) return "";
  target.pathname =
    target.pathname.replace(/\/+$/, "") +
    "/" +
    source.pathname.slice(marker.length);
  target.search = source.search;
  target.hash = "";
  return target.toString().replace(/%7B/gi, "{").replace(/%7D/gi, "}");
}
