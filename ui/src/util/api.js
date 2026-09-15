// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const APIUrl = import.meta.env.VITE_API_URL;
const APIMSubscriptionKey = import.meta.env.VITE_APIM_SUBSCRIPTION_KEY;
import { upsertUser } from "../AppHelper.js";
import { sanitizeRedirectPath } from "./validation.js";
import { fetchJsonResponse } from "./http.js";

export function buildUrl(endpoint) {
  const base = APIUrl + endpoint;
  if (APIMSubscriptionKey) {
    const sep = base.includes("?") ? "&" : "?";
    return base + sep + "subscription-key=" + APIMSubscriptionKey;
  }
  return base;
}

export async function apiValidateUser(setAppParams) {
  try {
    const staticAppStatus = await fetch("/.auth/me");
    const staticAppUserStatus = await staticAppStatus.json();
    if (staticAppUserStatus.clientPrincipal) {
      var response = await apiGet("GetUserById?userId=" + staticAppUserStatus.clientPrincipal.userDetails);
      if (response && response.status === "Active" || response && response.status === "Inactive") {
        const upsertUserObject = await upsertUser(response);
        if (upsertUserObject) {
          setAppParams((prevParams) => ({
            ...prevParams,
            userId: upsertUserObject.userId,
            // SWA principal object id — matches PublishedDataset.publishedByUser
            // so non-admin publishers are recognized as owners.
            identityId: staticAppUserStatus.clientPrincipal.userId,
            userRoles: upsertUserObject.userRoles,
            userSettings: upsertUserObject.settings,
            userStatus: upsertUserObject.status
          }));
        }
      } else if (response && response.status === "PendingAcceptance") {
        setAppParams((prevParams) => ({
          ...prevParams,
          userId: response.userId,
          identityId: staticAppUserStatus.clientPrincipal.userId,
          userRoles: response.userRoles,
          userSettings: response.settings,
          userStatus: response.status
        }));
      }
    }
  } catch (error) {
    console.error("Error validating user:", error);
  }
}

export async function apiLogout(redirectPath = "/") {
  try {
    // Constrain to a same-origin relative path so a crafted logout link can't
    // redirect users off-origin after sign-out (Security Review finding §8.6).
    const safePath = sanitizeRedirectPath(redirectPath);
    window.location.href = `/.auth/logout?post_logout_redirect_uri=${encodeURIComponent(safePath)}`;
  } catch (error) {
    console.error("Error logging out:", error);
  }
}

export async function apiGet(endpoint) {
  const response = await apiGetResponse(endpoint);
  return response.data;
}

export async function apiGetResponse(endpoint, options = {}) {
  try {
    return await fetchJsonResponse(buildUrl(endpoint), options);
  } catch (error) {
    if (error.name === "AbortError") throw error;
    console.error("Error fetching.:", error);
    throw new Error("Error fetching.");
  }
}

export async function apiPut(endpoint, data) {
  try {
    const response = await fetch(buildUrl(endpoint), {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    });

    if (response.status === 409) {
      return response.status;
    }

    // Accept any 2xx (e.g. 202 Accepted for async queue-message endpoints),
    // not just 200. Backward-compatible: existing 200 callers are unaffected.
    if (!response.ok) {
      // Surface the server's message instead of stringifying the Response
      // object (which renders as the useless "[object Response]"). Error
      // bodies are JSON `{ error: { code, message } }` (publishing routes) or
      // `{ error }` / `{ message }` elsewhere; fall back to the status code.
      let message = `Request failed (status ${response.status}).`;
      try {
        const body = await response.json();
        message =
          body?.error?.message || body?.error || body?.message || message;
      } catch {
        // Non-JSON error body — keep the status-based message.
      }
      throw new Error(message);
    }
    if (response.status === 204) {
      return null;
    }
    const message = await response.json();
    return message;

  } catch (error) {
    throw new Error(error.message || "Error updating element.");
  }
}

export async function apiPost(endpoint, data, isFormData = false) {
  try {
    const options = {
      method: 'POST',
      headers: isFormData ? {} : { 'Content-Type': 'application/json' },
      body: isFormData ? data : JSON.stringify(data)
    };

    const response = await fetch(buildUrl(endpoint), options);
    if (!response.ok) {
      const message = await response.json();
      throw new Error(message.error || `HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch {
    throw new Error("Error uploading chunk.");
  }
}

export async function apiDelete(endpoint) {
  try {
    const response = await fetch(buildUrl(endpoint), {
      method: 'DELETE'
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response;
  } catch {
    throw new Error("Error deleting element.");
  }
}