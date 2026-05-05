// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { apiGet } from "./api";

const AZURE_MAPS_CLIENT_ID = import.meta.env.VITE_AZURE_MAPS_CLIENT_ID;

/**
 * Fetches an Azure AD token for Azure Maps from the backend API.
 * Used by the Azure Maps SDK anonymous authentication flow.
 */
async function getAzureMapsToken(resolve, reject) {
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
