// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const APIUrl = import.meta.env.VITE_API_URL;
const APICodeParam = import.meta.env.VITE_APP_MASTER_KEY ? "code=" + import.meta.env.VITE_APP_MASTER_KEY : "";
import { upsertUser } from "../AppHelper.js";

function resolveVarConcatChar(text) {
  if (text === "") return "";
  return text.includes("?") ? "&" : "?";
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
            userRoles: upsertUserObject.userRoles,
            userSettings: upsertUserObject.settings,
            userStatus: upsertUserObject.status
          }));
        }
      } else if (response && response.status === "PendingAcceptance") {
        setAppParams((prevParams) => ({
          ...prevParams,
          userId: response.userId,
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
    window.location.href = `/.auth/logout?post_logout_redirect_uri=${encodeURIComponent(redirectPath)}`;
  } catch (error) {
    console.error("Error logging out:", error);
  }
}

export async function apiGet(endpoint) {
  try {
    const response = await fetch(APIUrl + endpoint + resolveVarConcatChar(endpoint) + APICodeParam);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error("Error fetching.:", error);
    throw new Error("Error fetching.");
  }
}

export async function apiPut(endpoint, data) {
  try {
    const response = await fetch(APIUrl + endpoint + resolveVarConcatChar(endpoint) + APICodeParam, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    });

    if (response.status === 409) {
      return response.status;
    }

    if (response.status !== 200 && response.status !== 409) {
      throw new Error(response);
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

    const response = await fetch(APIUrl + endpoint + resolveVarConcatChar(endpoint) + APICodeParam, options);
    if (!response.ok) {
      const message = await response.json();
      throw new Error(message.error || `HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    throw new Error("Error uploading chunk.");
  }
}

export async function apiDelete(endpoint) {
  try {
    const response = await fetch(APIUrl + endpoint + resolveVarConcatChar(endpoint) + APICodeParam, {
      method: 'DELETE'
    });
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response;
  } catch (error) {
    throw new Error("Error deleting element.");
  }
}