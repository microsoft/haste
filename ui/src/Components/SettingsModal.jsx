// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext } from "react";
import {
  Checkbox,
  Field,
  Text,
} from "@fluentui/react-components";

import { apiGet } from "../util/api";
import { updateUserSettings } from "../AppHelper";
import { AppContext } from "../AppContext";
import { useTheme } from "../util/ThemeContext";
import { PALETTES, getPalette } from "../util/theme";
import SectionModal from "./SectionModal";
import proptypes from "prop-types";

const SettingsModal = ({ onClose }) => {
  SettingsModal.propTypes = {
    onClose: proptypes.func.isRequired,
  };


  const { appParams, setIsLoading, setAppParams } = useContext(AppContext);
  const { palette, setPalette } = useTheme();

  async function handleGuidedTourToggle() {
    setIsLoading(true, "Toggling Guided Tour...");
    var response = await apiGet("GetUserById?userId=" + appParams.userId);
    await updateUserSettings(response, [{ disableGuidedTour: !appParams.userSettings.disableGuidedTour }]);
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        disableGuidedTour: !prevParams.userSettings.disableGuidedTour,
      },
    }));
    setIsLoading(false);
  }

  async function handlePaletteChange(key) {
    // Apply immediately for instant visual feedback (theme + localStorage).
    setPalette(key);
    // Optimistically reflect the choice in app state.
    setAppParams((prevParams) => ({
      ...prevParams,
      userSettings: {
        ...prevParams.userSettings,
        colorPalette: key,
      },
    }));
    // Persist to the user profile so it syncs across devices. Refetch first
    // to avoid clobbering concurrent settings changes (same pattern as above).
    setIsLoading(true, "Updating Color Palette...");
    try {
      const response = await apiGet("GetUserById?userId=" + appParams.userId);
      await updateUserSettings(response, [{ colorPalette: key }]);
    } catch (error) {
      // Non-blocking: the local (localStorage) value is the fallback if the
      // backend write fails, so the UI still reflects the user's choice.
      console.error("Error saving color palette preference:", error);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <SectionModal
      title={"User Preferences"}
      body={
        <>
          <div className="row mb-2">
            <div className="col-12">

            </div>
          </div>
          <div className="row mb-2 d-flex flex-column">
            <div className="col-12 d-flex flex-column mb-3">
              <Checkbox
                label="Guided Tour"
                checked={!appParams.userSettings.disableGuidedTour}
                onChange={handleGuidedTourToggle}
              />
              <Text className="pt-2" size={200}>
                When enabled, will provide step-by-step instructions to help you navigate through the application.
              </Text>
            </div>
            <hr />
            <div className="col-12 d-flex flex-column">
              <Field label="Color palette">
                <div className="settings-palette-swatches">
                  {PALETTES.map((p) => {
                    const isActive = p.key === palette;
                    return (
                      <button
                        key={p.key}
                        type="button"
                        className={
                          "settings-palette-swatch" +
                          (isActive ? " settings-palette-swatch--active" : "")
                        }
                        style={{ backgroundColor: getPalette(p.key).ramp[80] }}
                        aria-label={p.label}
                        aria-pressed={isActive}
                        title={p.label}
                        onClick={() => handlePaletteChange(p.key)}
                      />
                    );
                  })}
                </div>
              </Field>
              <Text className="pt-2" size={200}>
                Choose the accent color used across buttons, links, and highlights.
              </Text>
            </div>
          </div>
        </>
      }
      onClose={onClose}
      icon="Settings"
    />
  );
};

export default SettingsModal;
