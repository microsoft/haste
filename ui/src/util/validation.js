// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.


export function validateEmpty(key, value) {
  if (typeof value === "string" && value.trim() === "") {
    return `${key} can't be empty`;
  }

  if (value instanceof Date) {
    if (isNaN(value.getTime())) {
      return `${key} is not a valid date`;
    }
  }

  return "";
}


export function validateEmptyOrInvalid(isRequired = true, key, value) {
  var error = ""
  if (isRequired) {
    error = validateEmpty(key, value);
  }else{
    if (value === "") {
      return "";
    }
  }


  if (error === "") {
    const regex = /^[a-zA-Z0-9 ,._-]+$/;

    if (!regex.test(value)) {
      error = `${key} only allows letters, numbers, spaces, underscores, and hyphens`;
    }
  }

  return error;
}



export function validateAtLeastSomeNumber(key, value, number) {

  if (value.length < number) {
    return `${key} must have at least ${number} element${number > 1 ? "s" : ""}`;
  }
  return "";
}

export function validateIsUploading(preEventImageryUrls, postEventImageryUrls, userBuildingFootprintsUrls = []) {
  for (let i = 0; i < preEventImageryUrls.length; i++) {
    if (preEventImageryUrls[i].type === "file") {
      return true;
    }
  }

  for (let i = 0; i < postEventImageryUrls.length; i++) {
    if (postEventImageryUrls[i].type === "file") {
      return true;
    }
  }

  for (let i = 0; i < userBuildingFootprintsUrls.length; i++) {
    if (userBuildingFootprintsUrls[i].type === "file") {
      return true;
    }
  }

  return false;
}

export function validatePrimaryClasses(primaryClasses) {

  if (primaryClasses.length === 0) {
    return "At least one primary class is required";
  }

  for (let i = 0; i < primaryClasses.length; i++) {
    if (primaryClasses[i].name === "" || primaryClasses[i].color === "") {
      return "Primary classes must have a name and a color";
    }
  }

  const names = primaryClasses
    .map(pc => pc.name.trim().toLowerCase())
    .filter(name => name !== "");
  const uniqueNames = new Set(names);
  if (names.length !== uniqueNames.size) {
    return "Primary classes contain repeated names";
  }

  return false;
}

export function validateEventTypes(eventTypes){

  if(eventTypes.length === 0){
    return "At least one event type is required";
  }

  return false;
}

export function validateURL(url) {
  if (url.trim() === "") {
    return [false, "URL can't be empty"];
  } else {
    try {
      new URL(url);
      return [true, ""];
    } catch (e) {
      return [false, "Invalid URL format"];
    }
  }
}

// Keep in sync with hastelib/src/hastegeo/core/utils/url_allowlist.py.
const IMAGERY_URL_ALLOWED_HOST_DESCRIPTION =
  "Azure Blob Storage (*.blob.core.windows.net) or AWS S3 (*.amazonaws.com)";

const FOOTPRINT_URL_ALLOWED_HOST_DESCRIPTION =
  "Azure Blob Storage (*.blob.core.windows.net), AWS S3 (*.amazonaws.com), or the local upload host (in development)";

export function validateImageryUrlHost(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch (e) {
    return [false, "Invalid URL format"];
  }

  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return [false, `Unsupported URL scheme: ${parsed.protocol}`];
  }

  const host = parsed.hostname;
  if (!host) {
    return [false, "URL is missing host component"];
  }

  if (
    host === "blob.core.windows.net" ||
    host.endsWith(".blob.core.windows.net")
  ) {
    return [true, ""];
  }

  if (
    host === "s3.amazonaws.com" ||
    host.endsWith(".s3.amazonaws.com") ||
    host.endsWith(".amazonaws.com")
  ) {
    return [true, ""];
  }

  return [
    false,
    `URL host "${host}" is not on the allowlist. Allowed: ${IMAGERY_URL_ALLOWED_HOST_DESCRIPTION}.`,
  ];
}

// Same allowlist as validateImageryUrlHost plus the local upload host
// (so the URL returned by the chunked uploader works in local dev).
// Mirrors validate_footprint_url in url_allowlist.py.
export function validateFootprintUrlHost(url) {
  // First try the imagery hosts — accept immediately if it matches.
  const [imageryOk] = validateImageryUrlHost(url);
  if (imageryOk) {
    return [true, ""];
  }

  let parsed;
  try {
    parsed = new URL(url);
  } catch (e) {
    return [false, "Invalid URL format"];
  }

  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return [false, `Unsupported URL scheme: ${parsed.protocol}`];
  }

  const host = parsed.hostname;
  if (!host) {
    return [false, "URL is missing host component"];
  }

  // Local-dev fallback: allow azurite / localhost / 127.0.0.1 only when the UI
  // itself is running locally (dev stack). This avoids pre-approving loopback
  // URLs in deployed environments where the backend will reject them.
  const devHosts = new Set(["azurite", "localhost", "127.0.0.1"]);
  const runningLocally = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (runningLocally && devHosts.has(host)) {
    return [true, ""];
  }

  return [
    false,
    `URL host "${host}" is not on the allowlist. Allowed: ${FOOTPRINT_URL_ALLOWED_HOST_DESCRIPTION}.`,
  ];
}


// Schemes that can execute script or smuggle data — never allowed in an href
// or redirect target. Anything not resolving to http(s) (or a same-origin
// relative path, for safeHref) is treated as unsafe.
const UNSAFE_URL_SCHEME = /^\s*(javascript|data|vbscript|file):/i;

/**
 * True when `url` is a safe absolute external link target (http or https).
 * Rejects javascript:/data:/vbscript:/file: and protocol-relative ("//host")
 * URLs, which could execute script or redirect off-origin.
 */
export function isSafeExternalUrl(url) {
  if (typeof url !== "string" || url.trim() === "") return false;
  if (UNSAFE_URL_SCHEME.test(url)) return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch (e) {
    return false;
  }
}

/**
 * Returns `url` when it is safe to render as an href, otherwise undefined so
 * the caller can omit the attribute (Fluent's <Link> renders as plain text
 * without one). Accepts same-origin relative paths and safe absolute http(s)
 * URLs; rejects javascript:/data: schemes and protocol-relative ("//") URLs.
 */
export function safeHref(url) {
  if (typeof url !== "string" || url.trim() === "") return undefined;
  const trimmed = url.trim();
  if (UNSAFE_URL_SCHEME.test(trimmed)) return undefined;
  // Protocol-relative ("//evil.com") resolves off-origin — treat as unsafe.
  if (trimmed.startsWith("//")) return undefined;
  // Same-origin relative paths / fragments / queries are safe to keep as-is.
  if (
    trimmed.startsWith("/") ||
    trimmed.startsWith("./") ||
    trimmed.startsWith("../") ||
    trimmed.startsWith("#") ||
    trimmed.startsWith("?")
  ) {
    return url;
  }
  return isSafeExternalUrl(trimmed) ? url : undefined;
}

/**
 * Collapses a post-logout redirect target to a same-origin relative path.
 * Absolute URLs, protocol-relative URLs, and anything carrying a scheme become
 * "/". Closes the open-redirect on logout (Security Review finding §8.6).
 */
export function sanitizeRedirectPath(path) {
  if (typeof path !== "string" || path.trim() === "") return "/";
  // Browsers treat backslashes as forward slashes, so "/\evil.com" would
  // resolve like "//evil.com" — normalize before inspecting.
  const normalized = path.trim().replace(/\\/g, "/");
  if (normalized.startsWith("//")) return "/";
  // Any leading scheme ("http:", "javascript:", etc.) is an absolute target.
  if (/^[a-z][a-z0-9+.-]*:/i.test(normalized)) return "/";
  return normalized.startsWith("/") ? normalized : "/" + normalized;
}


export function validateFileType(file, acceptedFileTypes) {
  const fileExtension = file.split(".").pop().toLowerCase();
  const fileName = file.split("/").pop();
  if(acceptedFileTypes.includes(fileExtension)){
    return [true, ""];
  }else{
    return [false, `File ${fileName} is not of type ${acceptedFileTypes.join(", ")}`];
  }
}



export function validateEmail(key, value) {
  if (!value) {
    return `${key}'s email can't be empty`;
  }

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (!emailRegex.test(value)) {
    return "Invalid e-mail format";
  }

  return "";
}

export function validateTimestamp(line){
  const regex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+\d{2}:\d{2}/;
  return regex.test(line);
}

export function validateInt(key, value){
  var error = validateEmpty(key, value);
  if (error === "") {
    const regex = /^[0-9]+$/;
    if (!regex.test(value)) {
      error = `${key} must be an integer number`;
    }
  }
  return error;
}

export function validateFloat(key, value){
  var error = validateEmpty(key, value);
  if (error === "") {
    const regex = /^[0-9]+(\.[0-9]+)?$/;
    if (!regex.test(value)) {
      error = `${key} must be a float number`;
    }
  }
  return error;
}

export function validateRepeatedKeyInArray(key, array){

  for (let i = 0; i < array.length; i++) {
    if(array[i].key === "" || array[i].value === ""){
      return `Every ${key} line must have a key and a value`;
    }
  }

  const keys = array.map(item => item.key.trim()).filter(item => item !== "");
  const uniqueKeys = new Set(keys);
  if(keys.length !== uniqueKeys.size){
    return `${key} contains repeated keys`;
  }
  return "";
}