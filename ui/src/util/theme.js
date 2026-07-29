// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { createLightTheme, createDarkTheme } from "@fluentui/react-components";

const STORAGE_KEY = "haste-theme";
const PALETTE_STORAGE_KEY = "haste-palette";

// Traditional navy-blue brand ramp. brand.80 (#1f4e79) is the primary and
// meets WCAG AA contrast (~8:1 on white).
const hasteBrand = {
  10: "#050a10",
  20: "#0a141f",
  30: "#0f1f2f",
  40: "#14293f",
  50: "#193450",
  60: "#1e4062",
  70: "#1f4970",
  80: "#1f4e79",
  90: "#2c5f8c",
  100: "#3a6ea0",
  110: "#5486b3",
  120: "#7ba3c6",
  130: "#9db8d2",
  140: "#c0d3e5",
  150: "#dbe6f1",
  160: "#eef3f8",
};

const tealBrand = {
  10: "#041413",
  20: "#06201f",
  30: "#082b2a",
  40: "#0a3736",
  50: "#0c4342",
  60: "#0d5150",
  70: "#0e5e5d",
  80: "#0e6b6b",
  90: "#1a7d7c",
  100: "#2f9190",
  110: "#55a8a7",
  120: "#7cbfbe",
  130: "#9fd2d1",
  140: "#c3e3e2",
  150: "#ddefef",
  160: "#eef8f7",
};

const forestBrand = {
  10: "#071505",
  20: "#0c2109",
  30: "#10300d",
  40: "#153f11",
  50: "#1a4d15",
  60: "#205f1a",
  70: "#276e26",
  80: "#2f7d32",
  90: "#429646",
  100: "#57a95b",
  110: "#77bd7a",
  120: "#9ad19c",
  130: "#b6dfb8",
  140: "#d2ecd3",
  150: "#e6f5e7",
  160: "#f2faf2",
};

const violetBrand = {
  10: "#0d0716",
  20: "#150b25",
  30: "#1f1035",
  40: "#2a1545",
  50: "#351a55",
  60: "#472268",
  70: "#582f80",
  80: "#6b3fa0",
  90: "#7f57b1",
  100: "#9573c1",
  110: "#ac91d0",
  120: "#c3b0df",
  130: "#d5c8e9",
  140: "#e5daf1",
  150: "#f0ebf7",
  160: "#f8f4fb",
};

const crimsonBrand = {
  10: "#1a0405",
  20: "#290608",
  30: "#3b090b",
  40: "#4d0c0f",
  50: "#5f0f13",
  60: "#7a161b",
  70: "#8f1e23",
  80: "#a4262c",
  90: "#b8434a",
  100: "#cc626a",
  110: "#db858c",
  120: "#e8a8ae",
  130: "#f0c2c6",
  140: "#f6dadd",
  150: "#fbecee",
  160: "#fdf5f6",
};

// Curated palettes the user can pick from in Settings. The `key` is what
// gets persisted; `ramp` drives both the Fluent v9 theme and the custom
// CSS variables consumed by non-Fluent surfaces.
export const PALETTES = [
  { key: "navy", label: "Navy", ramp: hasteBrand },
  { key: "teal", label: "Teal", ramp: tealBrand },
  { key: "forest", label: "Forest", ramp: forestBrand },
  { key: "violet", label: "Violet", ramp: violetBrand },
  { key: "crimson", label: "Crimson", ramp: crimsonBrand },
];

export const DEFAULT_PALETTE = "navy";

/** Resolve a palette entry by key, falling back to the default. */
export function getPalette(key) {
  return (
    PALETTES.find((p) => p.key === key) ||
    PALETTES.find((p) => p.key === DEFAULT_PALETTE)
  );
}

/** Read the persisted palette key, defaulting to navy. */
export function getInitialPalette() {
  try {
    const stored = localStorage.getItem(PALETTE_STORAGE_KEY);
    return getPalette(stored).key;
  } catch {
    return DEFAULT_PALETTE;
  }
}

/**
 * Write the palette's brand ramp into the custom CSS variables used by
 * the non-Fluent surfaces (var(--primary-color) etc.). Fluent controls are
 * updated separately via <FluentProvider theme>.
 */
export function applyPaletteCssVars(key) {
  const { ramp } = getPalette(key);
  const root = document.documentElement;
  // Expose the full brand ramp so custom CSS can reference any tone.
  Object.keys(ramp).forEach((tone) => {
    root.style.setProperty(`--brand-${tone}`, ramp[tone]);
  });
  // Semantic aliases used throughout the custom stylesheet.
  root.style.setProperty("--primary-color", ramp[80]);
  root.style.setProperty("--box-border-color-dark", ramp[100]);
}

/** Persist and apply the chosen palette. Returns the resolved key. */
export function applyPalette(key) {
  const resolved = getPalette(key).key;
  applyPaletteCssVars(resolved);
  try {
    localStorage.setItem(PALETTE_STORAGE_KEY, resolved);
  } catch {
    /* ignore persistence errors */
  }
  return resolved;
}

/** Build the Fluent v9 light/dark themes for a given palette key. */
export function buildThemes(key) {
  const { ramp } = getPalette(key);
  return {
    light: createLightTheme(ramp),
    dark: createDarkTheme(ramp),
  };
}

// FluentUI v9 themes consumed by <FluentProvider>. These drive every
// migrated v9 control across the app.
export const v9LightTheme = createLightTheme(hasteBrand);
export const v9DarkTheme = createDarkTheme(hasteBrand);

/** Read the persisted theme, defaulting to light. */
export function getInitialTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Apply a theme ("light" | "dark") to the document and Fluent controls. */
export function applyTheme(theme) {
  const isDark = theme === "dark";
  document.documentElement.setAttribute(
    "data-theme",
    isDark ? "dark" : "light"
  );
  try {
    localStorage.setItem(STORAGE_KEY, isDark ? "dark" : "light");
  } catch {
    /* ignore persistence errors */
  }
  return isDark ? "dark" : "light";
}

/** Toggle between light and dark, returning the new theme. */
export function toggleTheme() {
  const next = getInitialTheme() === "dark" ? "light" : "dark";
  return applyTheme(next);
}
