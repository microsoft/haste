// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export const sourceTypeOptions = [
    { key: "n/a", text: "Unknown", visualizerText:"Unknown", showInDropdown: true, url: "" },
    { key: "rgb/no_processing", text: "RGB/NoProcessing", visualizerText:"RGB/NoProcessing", showInDropdown: true, url: "" },
    { key: "maxar", text: "Vantor", visualizerText:"Vantor Open Data Program", showInDropdown: true, url: "https://vantor.com/" },
    { key: "planet_scope", text: "Planet Scope", visualizerText:"Planet Scope", showInDropdown: true, url: "https://developers.planet.com/docs/data/planetscope" },
    { key: "planet_skysat", text: "Planet Skysat", visualizerText:"Planet Skysat", showInDropdown: true, url: "https://developers.planet.com/docs/data/skysat" },
    { key: "sentinel_2", text: "Sentinel 2", visualizerText:"Sentinel 2", showInDropdown: false, url: "https://docs.sentinel-hub.com/api/latest/data/sentinel-2-l2a" },
    { key: "azure_maps", text: "Azure Maps", visualizerText:"Azure Maps Basemap", showInDropdown: false, url: "https://azure.microsoft.com/en-us/products/azure-maps" },
];
