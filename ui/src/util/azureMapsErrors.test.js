// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { isOptionalAzureBasemapAuthError } from "./azureMapsErrors.js";

test("recognizes built-in basemap authentication errors in native and Atlas wrapper forms", () => {
  for (const tileset of ["microsoft.base", "microsoft.traffic.relative"]) {
    const url = `https://atlas.microsoft.com/map/tileset?api-version=2.1&tilesetId=${tileset}`;
    assert.equal(isOptionalAzureBasemapAuthError({ error: { status: 401, url } }), true);
    assert.equal(isOptionalAzureBasemapAuthError({ error: `AJAXError: (401): ${url}` }), true);
    assert.equal(isOptionalAzureBasemapAuthError(new Error(`AJAXError: (403): ${url}`)), true);
  }
});

test("does not hide prediction, uploaded imagery, custom tileset, or unknown failures", () => {
  for (const event of [
    { error: { status: 401, url: "http://localhost:7071/api/GetModelArtifact?kind=footprint_pmtiles" } },
    { error: { status: 401, url: "http://localhost:7071/api/titiler/cog/tiles/1/2/3" } },
    { error: { status: 401, url: "https://atlas.microsoft.com/map/tileset?tilesetId=custom.dataset" } },
    { error: { status: 401, url: "https://atlas.microsoft.com.example.test/map/tileset?tilesetId=microsoft.base" } },
    { error: { status: 500, url: "https://atlas.microsoft.com/map/tileset?tilesetId=microsoft.base" } },
    new Error("PMTiles decode failure"),
  ]) assert.equal(isOptionalAzureBasemapAuthError(event), false);
});
