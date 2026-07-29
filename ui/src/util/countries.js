// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

// Loads the country code -> country name map from the same reference file
// (world.geojson) used when creating/editing projects. The result is cached
// at module scope so the file is fetched at most once per session.

let cache = null;

export async function loadCountryNames() {
  if (cache) return cache;
  cache = (async () => {
    try {
      const response = await fetch(
        `${window.location.origin}/assets/json/world.geojson`
      );
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      const map = {};
      for (const feature of data.features ?? []) {
        if (feature.id != null) {
          map[feature.id] = feature.properties?.name ?? feature.id;
        }
      }
      return map;
    } catch (error) {
      console.error("Error loading country names:", error);
      return {};
    }
  })();
  return cache;
}
