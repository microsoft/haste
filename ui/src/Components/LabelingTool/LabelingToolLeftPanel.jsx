// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Button,
  Slider,
  Switch,
  Label,
  Field,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { useState, useEffect } from "react";
import { saveLabels, checkLabelsState } from "./LabelingToolHelper";

import PropType from "prop-types";
import { useNavigate } from "react-router-dom";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import {
  LABELING_TOOL_SHORTCUTS,
  shouldIgnoreShortcut,
} from "../keyboardShortcuts";

const LabelingToolLeftPanel = ({
  mapRef,
  drawingCount,
  preImageryRef,
  postImageryRef,
  hasUnsavedChanges,
  setDialog,
  setIsLoading,
  drawingManager,
  imageLayerId,
  labelingToolDataRef,
  setHasUnsavedChanges,
}) => {
  LabelingToolLeftPanel.propTypes = {
    mapRef: PropType.object.isRequired,
    drawingCount: PropType.number.isRequired,
    preImageryRef: PropType.object.isRequired,
    postImageryRef: PropType.object.isRequired,
    hasUnsavedChanges: PropType.bool.isRequired,
    setDialog: PropType.func.isRequired,
    setIsLoading: PropType.func.isRequired,
    drawingManager: PropType.object.isRequired,
    imageLayerId: PropType.string.isRequired,
    labelingToolDataRef: PropType.object.isRequired,
    setHasUnsavedChanges: PropType.func.isRequired,
  };

  const [eventImageryVisibilityState, setEventImageryVisibilityState] =
    useState(true);
  const [isImageryControlsOpen, setIsImageryControlsOpen] = useState(false);

  const [imageryValues, setImageryValues] = useState({
    opacity: 1,
    contrast: 0,
    hueRotation: 0,
    saturation: 0,
  });

  const updateValues = (key, value) => {
    try {
      switch (eventImageryVisibilityState) {
        case true:
          postImageryRef.current.setOptions({
            [key]: value,
          });
          break;
        case false:
          if (preImageryRef.current == null) return;
          preImageryRef.current.setOptions({
            [key]: value,
          });
          break;
        default:
          break;
      }

      setImageryValues({
        ...imageryValues,
        [key]: value,
      });
    } catch (error) {
      console.error("Error updating imagery values:", error);
    }
  };

  const resetControls = () => {
    try {
      setImageryValues({
        opacity: 1,
        contrast: 0,
        hueRotation: 0,
        saturation: 0,
      });

      switch (eventImageryVisibilityState) {
        case true:
          postImageryRef.current.setOptions({
            opacity: 1,
            contrast: 0,
            hueRotation: 0,
            saturation: 0,
          });
          break;
        case false:
          preImageryRef.current.setOptions({
            opacity: 1,
            contrast: 0,
            hueRotation: 0,
            saturation: 0,
          });
          break;
        default:
          break;
      }
    } catch (error) {
      console.error("Error resetting controls:", error);
    }
  };

  function getLayerById(currentMap, customId) {
    const layers = currentMap.current.layers.getLayers();
    return layers.find((layer) => layer.customId === customId);
  }

  function togglePostEventLayerVisibility(customId, isVisible) {
    const layer = getLayerById(mapRef, customId);
    if (layer) {
      layer.setOptions({ visible: isVisible });
    }
  }

  useEffect(() => {
    if (preImageryRef.current || postImageryRef.current) {
      try {

        // Layer visibility toggle
        if (preImageryRef.current !== null) {
          togglePostEventLayerVisibility(
            "preEventImageryLayer",
            !eventImageryVisibilityState
          );
        }

        togglePostEventLayerVisibility(
          "postEventImageryLayer",
          eventImageryVisibilityState
        );

        // Set imagery options based on the current state.
        if (eventImageryVisibilityState) {
          postImageryRef.current.setOptions({
            opacity: imageryValues.opacity,
            contrast: imageryValues.contrast,
            hueRotation: imageryValues.hueRotation,
            saturation: imageryValues.saturation,
          });
        } else {
          if (preImageryRef.current !== null) {
            preImageryRef.current.setOptions({
              opacity: imageryValues.opacity,
              contrast: imageryValues.contrast,
              hueRotation: imageryValues.hueRotation,
              saturation: imageryValues.saturation,
            });
          }
        }
      } catch (error) {
        console.error("Error toggling layer visibility:", error);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventImageryVisibilityState]);


  // A/D are the standard pre/post controls.
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (shouldIgnoreShortcut(e)) return;
      const key = e.key.toLowerCase();
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (key === "a") setEventImageryVisibilityState(false);
      else if (key === "d") setEventImageryVisibilityState(true);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  // Close the imagery settings panel when the user clicks on the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.events) return;
    const closeImageryControls = () => setIsImageryControlsOpen(false);
    map.events.add("click", closeImageryControls);
    return () => {
      map.events.remove("click", closeImageryControls);
    };
  }, [mapRef]);

  const navigate = useNavigate();

  const handleBackNavigation = () => {

    if (!checkLabelsState(drawingManager)) {
      setDialog("Important", `Please classify or remove invalid labels before leaving.`, [
        {
          type: "primary",
          key: "close",
          text: "Close",
          onClick: () => setDialog(),
        }
      ]);
      return false;
    }

    if (hasUnsavedChanges) {
      setDialog("Important", `Do you want to save changes before leaving?`, [
        {
          type: "primary",
          key: "yes",
          text: "Yes",
          onClick: saveAndLeave,
        },
        {
          type: "default",
          key: "no",
          text: "No",
          onClick: () => (setDialog(), navigate(-1)),
        },
        {
          type: "default",
          key: "cancel",
          text: "Cancel",
          onClick: () => setDialog(),
        },
      ]);
    } else {
      navigate(-1);
    }
  };

  const saveAndLeave = async () => {
    setDialog();
    const isSaved = await saveLabels(
      drawingManager,
      labelingToolDataRef,
      setIsLoading,
      setHasUnsavedChanges
    );
    if (isSaved) {
      navigate(-1);
    }
  };

  return (
    <>
      <div
        className="labeling-tool-surface labeling-navigation-controls"
      >
        <Button
          appearance="transparent"
          id="backButton"
          icon={<FluentIcon name="ChevronLeft" />}
          onClick={handleBackNavigation}
        >
          Back
        </Button>
        <Button
          appearance="subtle"
          id="imageryControlsButton"
          icon={<FluentIcon name="Slider" />}
          aria-expanded={isImageryControlsOpen}
          aria-controls="leftPanel"
          onClick={() => setIsImageryControlsOpen((isOpen) => !isOpen)}
        >
          Imagery
        </Button>
      </div>

      {isImageryControlsOpen && (
        <div
          className="labeling-tool-surface labeling-imagery-controls"
          id="leftPanel"
        >
              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Opacity</span>
                    <output>{Math.round(imageryValues.opacity * 100)}%</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateValues("opacity", data.value)}
                  value={imageryValues.opacity}
                />
              </Field>

              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Contrast</span>
                    <output>{imageryValues.contrast.toFixed(2)}</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
                  min={-1}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateValues("contrast", data.value)}
                  value={imageryValues.contrast}
                />
              </Field>

              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Hue Rotation</span>
                    <output>{imageryValues.hueRotation}&deg;</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
                  min={-180}
                  max={180}
                  step={1}
                  onChange={(e, data) => updateValues("hueRotation", data.value)}
                  value={imageryValues.hueRotation}
                />
              </Field>

              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Saturation</span>
                    <output>{imageryValues.saturation.toFixed(2)}</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
                  min={-1}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateValues("saturation", data.value)}
                  value={imageryValues.saturation}
                />
              </Field>


              <Button
                appearance="transparent"
                icon={<FluentIcon name="Slider" />}
                className="w-100 mb-2 mt-2"
                onClick={resetControls}
              >
                Reset controls
              </Button>

              <div id="postEventImagery">
                <Label className="mt-2 mb-2">Imagery</Label>
                <Switch
                  label={eventImageryVisibilityState ? "Post Event" : (labelingToolDataRef.current.imagery.preEventTileUrl ? "Pre Event" : "Basemap")}
                  checked={eventImageryVisibilityState}
                  onChange={(e, data) =>
                    setEventImageryVisibilityState(data.checked)
                  }
                />
              </div>
        </div>
      )}

      <div
        className="labeling-tool-surface labeling-count-badge"
        id="numberOfLabels"
      >
        Number of labels: {drawingCount}
      </div>
    </>
  );
};

export default LabelingToolLeftPanel;
