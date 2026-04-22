// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { apiGet } from "../util/api";
import { validateURL, validateFileType } from "../util/validation";
import { v4 as uuidv4 } from 'uuid';

const imageryOriginOptions = [
    { key: "url", text: "URL" },
    { key: "file", text: "File" },
]

export const sourceTypeOptions = [
    { key: "n/a", text: "Unknown", visualizerText:"Unknown", showInDropdown: true, url: "" },
    { key: "rgb/no_processing", text: "RGB/NoProcessing", visualizerText:"RGB/NoProcessing", showInDropdown: true, url: "" },
    { key: "mercy_corps", text: "Custom - Mercy Corps", visualizerText:"Custom - Mercy Corps", showInDropdown: true, url: "" },
    { key: "maxar", text: "Maxar", visualizerText:"Maxar Open Data Program", showInDropdown: true, url: "https://maxar.com/" },
    { key: "planet_scope", text: "Planet Scope", visualizerText:"Planet Scope", showInDropdown: true, url: "https://developers.planet.com/docs/data/planetscope" },
    { key: "planet_skysat", text: "Planet Skysat", visualizerText:"Planet Skysat", showInDropdown: true, url: "https://developers.planet.com/docs/data/skysat" },
    { key: "sentinel_2", text: "Sentinel 2", visualizerText:"Sentinel 2", showInDropdown: false, url: "https://docs.sentinel-hub.com/api/latest/data/sentinel-2-l2a" },
    { key: "azure_maps", text: "Azure Maps", visualizerText:"Azure Maps Basemap", showInDropdown: false, url: "https://azure.microsoft.com/en-us/products/azure-maps" },
];

export async function createComponentDefaultState(imageLayerId, projectId) {
    try {
        //const settings = await apiGet("GetAdminSettings");
        var imageLayerToEdit = null;
        if (imageLayerId) {
            imageLayerToEdit = await apiGet("GetLayerDetailView?projectId=" + projectId + "&imageLayerId=" + imageLayerId);
        }

        // Get Project Name
        const project = await apiGet("GetProjectDetails?projectId=" + projectId);

        const tempState = imageLayerToEdit
            ? {
                ...imageLayerToEdit,
                nameError: "",
                description: imageLayerToEdit.description,
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
            }
            : {
                imageLayerId: "",
                projectId: projectId,
                name: "",
                nameError: "",
                description: "",
                preEventImageryUrls: [],
                postEventImageryUrls: [],
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

            }

        return tempState;
    } catch (error) {
        console.error("Error inializing component:", error);
    }

}

function getSectionHeaderProperties(projectName, projectId, imageLayerId) {
    return {
        iconName: "OpenFolderHorizontal",
        path: [
            { name: "Projects", link: "/projects" },
            { name: projectName, link: "/project/" + projectId },
            {
                name: imageLayerId ? "Edit Image Layer" : "Create Image Layer",
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


    if (urlIsValid[0]) {
        if (componentState[field].some(item => item.value === url)) {
            setComponentState({
                ...componentState,
                [errorField]: "URL already exists in the list.",
            });
            return false;
        } else {
            setComponentState({
                ...componentState,
                [field]: [...componentState[field], { id: id, type: "url", value: url }],
                [errorField]: "",
            });
            return true;
        }
    } else {
        setComponentState({
            ...componentState,
            [errorField]: urlIsValid[1],
        });
        return false;
    }
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
    setComponentState({
        ...componentState,
        [field]: componentState[field].filter((u) => u.id !== id),
    });
};

export const convertFileIntoUrl = (setComponentState, componentState, file, url, field) => {
    const tempFile = { id: file.id, value: url, type: "url", name: file.value.name };

    const updatedImageryUrls = componentState[field].map((item) => {
        if (item.id === file.id) {
            return tempFile;
        }
        return item;
    });
    setComponentState({
        ...componentState,
        [field]: updatedImageryUrls,
    });
}

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