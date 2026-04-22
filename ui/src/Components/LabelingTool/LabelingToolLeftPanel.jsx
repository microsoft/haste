// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  ActionButton,
  Slider,
  Toggle,
  Label,
} from "@fluentui/react";
import { useState, useEffect } from "react";
import { saveLabels, checkLabelsState } from "./LabelingToolHelper";

import PropType from "prop-types";
import { useNavigate } from "react-router-dom";

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
  appParams
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
    appParams: PropType.object.isRequired,
  };

  const [eventImageryVisibilityState, setEventImageryVisibilityState] =
    useState(true);

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


  // need a listener to update the post event imagery layer visibility on ctrl + p
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.ctrlKey && e.altKey && e.key === "c") {
        setEventImageryVisibilityState((prevState) => !prevState);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [eventImageryVisibilityState]);

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
        style={{
          position: "absolute",
          left: 10,
          top: 10,
          backgroundColor: "rgba(255, 255, 255, 1)",
          padding: "5px 10px",
          borderRadius: "5px",
          zIndex: 1000,
        }}
        className=""
      >
        <div>
          <ActionButton
            id="backButton"
            iconProps={{ iconName: "ChevronLeft" }}
            onClick={handleBackNavigation}
          >
            Back
          </ActionButton>

          {appParams.bootstrapBreakpoint >= 3 && (
            <div
              style={{
                borderTop: "1px solid rgba(0, 0, 0, 0.1)",
                paddingTop: "12px",
                marginTop: "5px",
              }}
              id="leftPanel"
            >
              <Slider
                label="Opacity"
                min={0}
                max={1}
                step={0.01}
                defaultValue={100}
                showValue={false}
                onChange={(value) => updateValues("opacity", value)}
                value={imageryValues.opacity}
              />

              <Slider
                label="Contrast"
                min={-1}
                max={1}
                step={0.01}
                defaultValue={0}
                showValue={false}
                onChange={(value) => updateValues("contrast", value)}
                value={imageryValues.contrast}
              />

              <Slider
                label="Hue Rotation"
                min={-180}
                max={180}
                step={1}
                defaultValue={0}
                showValue={false}
                onChange={(value) => updateValues("hueRotation", value)}
                value={imageryValues.hueRotation}
              />

              <Slider
                label="Saturation"
                min={-1}
                max={1}
                step={0.01}
                defaultValue={0}
                showValue={false}
                onChange={(value) => updateValues("saturation", value)}
                value={imageryValues.saturation}
              />


              <ActionButton
                iconProps={{ iconName: "Slider" }}
                className="w-100 mb-2 mt-2"
                onClick={resetControls}
              >
                Reset controls
              </ActionButton>

              <div id="postEventImagery">
                <Label className="mt-2 mb-2">Imagery</Label>
                <Toggle
                  onText="Post Event"
                  offText={labelingToolDataRef.current.imagery.preEventTileUrl ? "Pre Event" : "Basemap"}
                  checked={eventImageryVisibilityState}
                  onChange={(e, checked) =>
                    setEventImageryVisibilityState(checked)
                  }
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 55,
          bottom: 38,
          backgroundColor: "rgba(255, 255, 255, 1)",
          padding: "5px 10px",
          borderRadius: "5px",
          zIndex: 1000,
        }}
        id="numberOfLabels"
      >
        Number of labels: {drawingCount}
      </div>
    </>
  );
};

export default LabelingToolLeftPanel;
