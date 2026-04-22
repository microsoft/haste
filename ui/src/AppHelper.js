// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { apiGet, apiPut } from "./util/api";


export async function upsertUser(user) {
    try {
        // Update user details if they already exist
       
        const userObject = {
            userId: user.userId,
            email: user.userId,
            name: user.userId,
            userRoles: user.userRoles,
            identityProvider: user.identityProvider,
            settings: user.settings || {}
        };

        return apiPut("PutUser", { user: userObject, action: "update" });
    } catch (error) {
        console.error("Error upserting user:", error);
    }
};

export async function updateUserSettings(response, settings) {
    try {
        if (response) {
            // Update the user settings in the API
            settings.forEach((setting) => {
                response.settings[Object.keys(setting)[0]] = Object.values(setting)[0];
            });

            await apiPut("PutUser", { user: response, action: "update" });
        } else {
            console.error("User settings not found or invalid response.");
        }
    } catch (error) {
        console.error("Error updating user settings:", error);
    }
}