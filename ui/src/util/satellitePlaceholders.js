// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

// Stylized satellite-imagery placeholders shown while real AOI thumbnails are
// not yet wired up. Vite resolves each import to a bundled asset URL.
import sat1 from "../assets/img/satellite-1.svg";
import sat2 from "../assets/img/satellite-2.svg";
import sat3 from "../assets/img/satellite-3.svg";
import sat4 from "../assets/img/satellite-4.svg";
import sat5 from "../assets/img/satellite-5.svg";
import sat6 from "../assets/img/satellite-6.svg";

const SATELLITE_PLACEHOLDERS = [sat1, sat2, sat3, sat4, sat5, sat6];

// Deterministic pick so a given image layer always shows the same tile,
// regardless of sort/filter order. Falls back to index when no key is given.
export function satellitePlaceholder(key, fallbackIndex = 0) {
  const source =
    typeof key === "string" && key.length > 0 ? key : String(fallbackIndex);
  let hash = 0;
  for (let i = 0; i < source.length; i++) {
    hash = (hash * 31 + source.charCodeAt(i)) | 0;
  }
  const idx = Math.abs(hash) % SATELLITE_PLACEHOLDERS.length;
  return SATELLITE_PLACEHOLDERS[idx];
}
