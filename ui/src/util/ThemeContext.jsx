// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { createContext, useContext, useState, useCallback, useMemo } from "react";
import PropTypes from "prop-types";
import { FluentProvider } from "@fluentui/react-components";
import {
  getInitialTheme,
  applyTheme,
  getInitialPalette,
  applyPalette,
  buildThemes,
} from "./theme";

const ThemeContext = createContext({
  mode: "light",
  isDark: false,
  toggle: () => {},
  setTheme: () => {},
  palette: "navy",
  setPalette: () => {},
});

/**
 * Wraps the app in a v9 <FluentProvider> and exposes the current theme
 * mode plus a toggle. Also keeps v8 controls (loadTheme) and the custom
 * CSS `data-theme` attribute in sync during the v8 -> v9 transition.
 */
export function ThemeProvider({ children }) {
  const [mode, setMode] = useState(() => getInitialTheme());
  const [palette, setPaletteState] = useState(() => getInitialPalette());

  const toggle = useCallback(() => {
    setMode((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      applyTheme(next); // persists + sets data-theme + v8 loadTheme
      return next;
    });
  }, []);

  // Apply an explicit theme. Anything other than "dark" falls back to light.
  const setTheme = useCallback((theme) => {
    const resolved = theme === "dark" ? "dark" : "light";
    applyTheme(resolved);
    setMode(resolved);
  }, []);

  const setPalette = useCallback((key) => {
    const resolved = applyPalette(key); // persists + updates CSS vars
    setPaletteState(resolved);
  }, []);

  const isDark = mode === "dark";

  const { light, dark } = useMemo(() => buildThemes(palette), [palette]);

  return (
    <ThemeContext.Provider value={{ mode, isDark, toggle, setTheme, palette, setPalette }}>
      <FluentProvider
        theme={isDark ? dark : light}
        style={{ height: "100%", background: "transparent" }}
      >
        {children}
      </FluentProvider>
    </ThemeContext.Provider>
  );
}

ThemeProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

/** Access the current theme mode and toggle. */
export function useTheme() {
  return useContext(ThemeContext);
}
