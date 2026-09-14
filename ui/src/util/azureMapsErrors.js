// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export function isOptionalAzureBasemapAuthError(event) {
  const error = event?.error ?? event;
  const message = typeof error === "string" ? error : error?.message ?? event?.message ?? "";
  const url = error?.url ?? event?.url ?? message.match(/https?:\/\/[^\s"'<>]+/)?.[0];
  const prefix = url && message.includes(url) ? message.slice(0, message.indexOf(url)) : message;
  const status = Number(error?.status ?? event?.status ?? prefix.match(/\b(401|403)\b/)?.[1]);
  if (!url || ![401, 403].includes(status)) return false;
  let parsed;
  try { parsed = new URL(url); } catch { return false; }
  return (parsed.hostname === "atlas.microsoft.com" || parsed.hostname.endsWith(".atlas.microsoft.com")) &&
    /^\/map\/(?:tileset|tile)\/?$/.test(parsed.pathname) &&
    (parsed.searchParams.get("tilesetId") || "").startsWith("microsoft.");
}
