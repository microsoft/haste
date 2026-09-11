// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { apiGet } from "../util/api";
import {
  validateURL,
  validateImageryUrlHost,
  validateFootprintUrlHost,
  validateFileType,
} from "../util/validation";
import { v4 as uuidv4 } from 'uuid';
import {
  sourceTypeOptions,
  normalizeSourceTypeKey,
} from "./sourceTypeOptions.js";
import { sourceImageryRef } from "./OpenDataCatalog/openDataCatalog.js";
import { loadImageLayerFormData } from "./loadImageLayerFormData.js";

export { sourceTypeOptions, normalizeSourceTypeKey };

const imageryOriginOptions = [
    { key: "url", text: "URL" },
    { key: "file", text: "File" },
]

export async function createComponentDefaultState(imageLayerId, projectId) {
    try {
        const { imageLayerToEdit, project } = await loadImageLayerFormData(
            imageLayerId,
            projectId,
            apiGet,
        );

        const tempState = imageLayerToEdit
            ? {
                ...imageLayerToEdit,
                nameError: "",
                description: imageLayerToEdit.description,
                workflowType: imageLayerToEdit.workflowType || "standard",
                preEventImageryUrls: convertImageryUrlsToFormFormat(imageLayerToEdit.preEventImageryUrls),
                postEventImageryUrls: convertImageryUrlsToFormFormat(imageLayerToEdit.postEventImageryUrls),
                format: imageLayerToEdit.format,
                formatError: "",
                sourceTypePreEvent: imageLayerToEdit.sourceTypePreEvent,
                sourceTypePreEventError: "",
                sourceTypePostEvent: imageLayerToEdit.sourceTypePostEvent,
                sourceTypePostEventError: "",
                normalizationFactor: imageLayerToEdit.normalizationFactor,
                normalizationFactorError: "",
                imageryCaptureDatePreEvent: imageLayerToEdit.imageryCaptureDatePreEvent ? imageLayerToEdit.imageryCaptureDatePreEvent : "",
                imageryCaptureDatePreEventError: "",
                imageryCaptureDatePostEvent: imageLayerToEdit.imageryCaptureDatePostEvent ? imageLayerToEdit.imageryCaptureDatePostEvent : "",
                imageryCaptureDatePostEventError: "",
                sourceTypeList: sourceTypeOptions,
                sectionHeaderProperties: getSectionHeaderProperties(project.name, projectId, imageLayerId),
                currentPreEventImageryUrlControl: imageryOriginOptions[0].key,
                currentPreEventImageryUrlControlError: "",
                currentPostEventImageryUrlControl: imageryOriginOptions[0].key,
                currentPostEventImageryUrlControlError: "",
                imageryOriginOptions: imageryOriginOptions,
                projectName: project.name,
                // Custom building-footprint state — display only on edit
                // (the field is create-only; we show what the layer was
                // created with but don't allow changes).
                userBuildingFootprintsEnabled: !!imageLayerToEdit.userBuildingFootprintsUrl,
                userBuildingFootprintsUrls: imageLayerToEdit.userBuildingFootprintsUrl
                    ? [{ id: uuidv4(), type: "url", value: imageLayerToEdit.userBuildingFootprintsUrl, name: "" }]
                    : [],
                currentUserBuildingFootprintsControl: imageryOriginOptions[0].key,
                currentUserBuildingFootprintsControlError: "",
                // Server-side clip AOI [w, s, e, n] EPSG:4326 (Open Data Catalog).
                clipBbox: imageLayerToEdit.clipBbox || null,
            }
            : {
                imageLayerId: "",
                projectId: projectId,
                name: "",
                nameError: "",
                description: "",
                workflowType: "standard",
                preEventImageryUrls: [],
                postEventImageryUrls: [],
                // Source-imagery provenance captured from the Open Data Catalog.
                sourceImageryReferences: [],
                format: "tif",
                formatError: "",
                sourceTypePreEvent: "n/a", // Unknown
                sourceTypePreEventError: "",
                sourceTypePostEvent: "n/a", // Unknown
                sourceTypePostEventError: "",
                normalizationFactor: "0",
                normalizationFactorError: "",
                imageryCaptureDatePreEvent: "",
                imageryCaptureDatePreEventError: "",
                imageryCaptureDatePostEvent: "",
                imageryCaptureDatePostEventError: "",
                sourceTypeList: sourceTypeOptions,
                sectionHeaderProperties: getSectionHeaderProperties(project.name, projectId, imageLayerId),
                currentPreEventImageryUrlControl: imageryOriginOptions[0].key,
                currentPreEventImageryUrlControlError: "",
                currentPostEventImageryUrlControl: imageryOriginOptions[0].key,
                currentPostEventImageryUrlControlError: "",
                imageryOriginOptions: imageryOriginOptions,
                projectName: project.name,
                // Custom building-footprint state (optional panel below
                // pre-event imagery on the Create Image Layer form).
                userBuildingFootprintsEnabled: false,
                userBuildingFootprintsUrls: [],
                currentUserBuildingFootprintsControl: imageryOriginOptions[0].key,
                currentUserBuildingFootprintsControlError: "",
                // Server-side clip AOI [w, s, e, n] EPSG:4326 (Open Data Catalog).
                clipBbox: null,
            }

        return tempState;
    } catch (error) {
        console.error("Error inializing component:", error);
        throw error;
    }

}

function getSectionHeaderProperties(projectName, projectId, imageLayerId) {
    return {
        iconName: "OpenFolderHorizontal",
        path: [
            { name: "Projects", link: "/projects" },
            { name: projectName, link: "/project/" + projectId },
            {
                name: imageLayerId ? "Edit Image Layer" : "New Image Layer",
                link: "",
            },
        ],
        links: [],
        filter: false,
    };
}

export const getUrlList = (eventImageryUrls) => {
    return eventImageryUrls.map((item) => {
        if (item.type === "url") {
            return item.value;
        }
        return "";
    });
};

export const addUrlToEventImageryArray = (setComponentState, componentState, URL, field, errorField) => {
    const url = URL.trim();
    const urlIsValid = validateURL(url);
    const id = uuidv4();

    if (!urlIsValid[0]) {
        setComponentState({
            ...componentState,
            [errorField]: urlIsValid[1],
        });
        return false;
    }

    const hostIsValid = validateImageryUrlHost(url);
    if (!hostIsValid[0]) {
        setComponentState({
            ...componentState,
            [errorField]: hostIsValid[1],
        });
        return false;
    }

    if (componentState[field].some(item => item.value === url)) {
        setComponentState({
            ...componentState,
            [errorField]: "URL already exists in the list.",
        });
        return false;
    }

    setComponentState({
        ...componentState,
        [field]: [...componentState[field], { id: id, type: "url", value: url }],
        [errorField]: "",
    });
    return true;
};

// Building-footprint URLs use a slightly wider allowlist than imagery
// (they may legitimately come from the local chunked-upload endpoint),
// and only one entry is allowed at a time.
export const addUrlToFootprintArray = (setComponentState, componentState, URL, field, errorField) => {
    const url = URL.trim();
    const urlIsValid = validateURL(url);
    const id = uuidv4();

    if (!urlIsValid[0]) {
        setComponentState({
            ...componentState,
            [errorField]: urlIsValid[1],
        });
        return false;
    }

    const hostIsValid = validateFootprintUrlHost(url);
    if (!hostIsValid[0]) {
        setComponentState({
            ...componentState,
            [errorField]: hostIsValid[1],
        });
        return false;
    }

    if ((componentState[field] || []).length > 0) {
        setComponentState({
            ...componentState,
            [errorField]: "Only one building-footprints GPKG can be added; remove the existing entry first.",
        });
        return false;
    }

    setComponentState({
        ...componentState,
        [field]: [{ id: id, type: "url", value: url }],
        [errorField]: "",
    });
    return true;
};


// Add a scene picked from the Open Data Catalog explorer to a pre/post
// imagery array. Appends the COG URL AND (v1 auto-fill) sets the matching
// source-type dropdown and imagery capture date — but only when those fields
// are still empty/default, so a user's own entries are never clobbered.
//
// `field` is "preEventImageryUrls" | "postEventImageryUrls"; the sibling
// source-type / capture-date field names are derived from it. Returns a
// { ok, error } result so the caller can surface a message inline.
export const addSceneToEventImagery = (setComponentState, componentState, scene, field) => {
    const url = (scene?.cogUrl || "").trim();
    if (!url) {
        return { ok: false, error: "This scene has no downloadable COG yet." };
    }

    const urlIsValid = validateURL(url);
    if (!urlIsValid[0]) {
        return { ok: false, error: urlIsValid[1] };
    }

    const hostIsValid = validateImageryUrlHost(url);
    if (!hostIsValid[0]) {
        return { ok: false, error: hostIsValid[1] };
    }

    if (componentState[field].some((item) => item.value === url)) {
        return { ok: false, error: "This scene is already added." };
    }

    const isPre = field === "preEventImageryUrls";
    const sourceTypeField = isPre ? "sourceTypePreEvent" : "sourceTypePostEvent";
    const captureDateField = isPre
        ? "imageryCaptureDatePreEvent"
        : "imageryCaptureDatePostEvent";

    const patch = {
        ...componentState,
        [field]: [
            ...componentState[field],
            { id: uuidv4(), type: "url", value: url, name: scene.title || "" },
        ],
    };

    // Capture source-imagery provenance when the scene is from an open-data
    // program (fail-safe: null for anything else). Deduped by STAC item href.
    const ref = sourceImageryRef(scene, isPre ? "pre" : "post");
    if (ref) {
        const existing = componentState.sourceImageryReferences || [];
        if (!existing.some((r) => r.href === ref.href)) {
            patch.sourceImageryReferences = [...existing, ref];
        }
    }

    // Only auto-fill source type when still at the "Unknown" default.
    if (scene.sourceTypeKey && (componentState[sourceTypeField] === "n/a" || !componentState[sourceTypeField])) {
        patch[sourceTypeField] = scene.sourceTypeKey;
    }

    // Only auto-fill capture date when the user hasn't set one.
    if (scene.datetime && !componentState[captureDateField]) {
        const parsed = new Date(scene.datetime);
        if (!isNaN(parsed.getTime())) {
            patch[captureDateField] = parsed;
        }
    }

    setComponentState(patch);
    return { ok: true, error: "" };
};

export const addFileToEventImageryArray = (files, acceptedFileTypes, componentState, setComponentState, field, errorField) => {

    var invalidFiles = [];
    var filesToAdd = [];

    try {

        for (let i = 0; i < files.length; i++) {
            const fileIsValid = validateFileType(files[i].name, acceptedFileTypes);

            if (!fileIsValid[0]) {
                invalidFiles.push(files[i].name);
            } else {
                const id = uuidv4();
                filesToAdd.push({ id: id, type: "file", value: files[i] });
            }
        }



        if (filesToAdd.length > 0) {
            var message = "";

            if (invalidFiles.length > 0) {
                message = "Some of the files have unsupported format: " + invalidFiles.join(", ");
            }

            setComponentState({
                ...componentState,
                [field]: [
                    ...componentState[field],
                    ...filesToAdd,
                ],
                [errorField]: message,
            });
        } else {
            setComponentState({
                ...componentState,
                [errorField]: "None of the selected files had a valid format.",
            });
            return false;
        }
    } catch (error) {
        console.error("Error adding file to event imagery array:", error);
        return false;
    }
};


export const removeUrlFromEventImageryArray = (id, setComponentState, componentState, field) => {
    const removed = componentState[field].find((u) => u.id === id);
    const removedUrl = removed?.value;
    // Drop any captured source-imagery reference tied to the removed COG so
    // provenance stays in sync with the imagery actually kept on the layer.
    const refs = componentState.sourceImageryReferences || [];
    const nextRefs = removedUrl
        ? refs.filter((r) => r.sourceUrl !== removedUrl)
        : refs;
    setComponentState({
        ...componentState,
        [field]: componentState[field].filter((u) => u.id !== id),
        ...(refs.length !== nextRefs.length
            ? { sourceImageryReferences: nextRefs }
            : {}),
    });
};

// Single-file variant for the building-footprints panel: enforces exactly
// one entry and validates the .gpkg extension.
export const addFootprintFileToArray = (files, componentState, setComponentState, field, errorField) => {
    if (!files || files.length === 0) {
        setComponentState({
            ...componentState,
            [errorField]: "Select a .gpkg file to upload.",
        });
        return false;
    }
    if ((componentState[field] || []).length > 0) {
        setComponentState({
            ...componentState,
            [errorField]: "Only one building-footprints GPKG can be added; remove the existing entry first.",
        });
        return false;
    }
    // Single-file picker, but be defensive.
    const file = files[0];
    const isValid = validateFileType(file.name, ["gpkg"]);
    if (!isValid[0]) {
        setComponentState({
            ...componentState,
            [errorField]: isValid[1],
        });
        return false;
    }
    setComponentState({
        ...componentState,
        [field]: [{ id: uuidv4(), type: "file", value: file }],
        [errorField]: "",
    });
    return true;
};

export const convertFileIntoUrl = (setComponentState, componentState, file, url, field) => {
    const tempFile = { id: file.id, value: url, type: "url", name: file.value.name };

    // Use the functional-update form so that any concurrent edits the
    // user makes during a long upload aren't overwritten by stale state
    // captured when the uploader first mounted.
    setComponentState((prev) => ({
        ...prev,
        [field]: prev[field].map((item) => (item.id === file.id ? tempFile : item)),
    }));
};

function convertImageryUrlsToFormFormat(imageryUrls) {
    var formFormat = [];
    imageryUrls.forEach((item) => {
        const id = uuidv4();
        formFormat.push({ id: id, value: item, type: "url", name: "" });
    });
    return formFormat;
}

export const onFormChange = (value, key, setComponentState, componentState) => {
    if (key === "imageryCaptureDatePreEvent" || key === "imageryCaptureDatePostEvent") {
        value = value ? new Date(value) : "";
    }
    setComponentState({ ...componentState, [key]: value });
};