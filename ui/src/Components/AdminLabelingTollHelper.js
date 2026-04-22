// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { apiGet } from "../util/api";

export async function createComponentDefaultState() {
    try {
        const settings = await apiGet("GetAdminSettings");
        const tempState = {
            ...settings.labelingToolSettings,
            nameError: "",
            descriptionError: "",
            affectedCountriesError: "",
            primaryClassesError: "",
        };

        return tempState;

    } catch {
        return null;
    }
}
