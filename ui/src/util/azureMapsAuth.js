// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { apiGet } from "./api";

const AZURE_MAPS_CLIENT_ID = import.meta.env.VITE_AZURE_MAPS_CLIENT_ID;

const isPlaceholderClientId =
  !AZURE_MAPS_CLIENT_ID ||
  AZURE_MAPS_CLIENT_ID === "placeholder" ||
  AZURE_MAPS_CLIENT_ID.startsWith("placeholder");

/**
 * Fetches an Azure AD token for Azure Maps from the backend API.
 * Used by the Azure Maps SDK anonymous authentication flow.
 *
 * In local development VITE_AZURE_MAPS_CLIENT_ID is left at its placeholder
 * default and the backend GetAzureMapsToken endpoint cannot mint a token
 * (no managed identity, no az login cache mounted). Resolving with a fake
 * non-empty JWT (instead of "") short-circuits the SDK so the labeling tool
 * still initializes — empty strings are rejected as auth failure and the
 * map control stops firing its "ready" event, which prevents zoom controls,
 * custom TileLayers, and study-area outlines from being added.
 *
 * The token isn't actually sent to atlas.microsoft.com because callers also
 * pick a basemap style that doesn't require an Azure Maps subscription
 * (see isAzureMapsPlaceholder usage in LabelingTool.jsx).
 */
async function getAzureMapsToken(resolve, reject) {
  if (isPlaceholderClientId) {
    // RFC 7519-shaped placeholder. Header={"alg":"none","typ":"JWT"},
    // payload={"sub":"haste-local-dev","exp":4102444800} (year 2100).
    resolve(
      "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0." +
        "eyJzdWIiOiJoYXN0ZS1sb2NhbC1kZXYiLCJleHAiOjQxMDI0NDQ4MDB9."
    );
    return;
  }
  try {
    const response = await apiGet("GetAzureMapsToken");
    resolve(response.access_token);
  } catch (error) {
    reject(error);
  }
}

/**
 * Returns the authOptions object for atlas.Map initialization
 * using anonymous auth with managed identity.
 */
export function getAzureMapsAuthOptions() {
  return {
    authType: "anonymous",
    clientId: AZURE_MAPS_CLIENT_ID,
    getToken: getAzureMapsToken,
  };
}

/**
 * True when the deployment has not been wired up to a real Azure Maps account
 * (i.e. local docker-compose dev). Callers should use the "blank" map style
 * in this case so the map control can initialize without fetching styles
 * from atlas.microsoft.com (which requires a real token).
 */
export const isAzureMapsPlaceholder = isPlaceholderClientId;
