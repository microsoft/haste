// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// The small-screen version of the results page overlay: imagery details for
// whichever side of the swipe is showing, plus the same layer toggles the
// InfoPanel offers on the desktop layout. The layer rows come from the same
// pure visualizerLayerOptions() list, so a model with no damage raster shows
// no checkbox for one here either.
import {
  Checkbox,
  Button,
  Text,
  Switch,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";


import { useState } from "react";
import PropType from "prop-types";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { VISUALIZER_SHORTCUTS } from "../keyboardShortcuts";

const VisualizerInformationMobile = ({
  visualizerResults,
  convertPreOrPostEventImageryDate,
  convertPreOrPostEventImagerySource,
  setSwipeStateMobile,
  swipeStateMobile,
  layerOptions,
  layerVisibility,
  onLayerVisibilityChange,
  surfaceClassName,
}) => {
  const [panelVisibility, setPanelVisibility] = useState("d-none");

  const togglePanelVisibility = () => {
    if (panelVisibility === "d-none") {
      setPanelVisibility("");
    } else {
      setPanelVisibility("d-none");
    }
  }
  return (
    <>
      <div
        className={`absolute-labels post-disaster visualizer-information-mobile${
          panelVisibility === "" ? " visualizer-information-mobile--expanded" : ""
        } d-block d-lg-none ${surfaceClassName}`}
      >
        <Button
          appearance="transparent"
          icon={<FluentIcon name={panelVisibility === "" ? "cancel" : "info"} />}
          onClick={() => {
            togglePanelVisibility();
          }}
        >
          <span className="ms-2 fw-semibold">Info</span>
        </Button>

        <div
          className={`${panelVisibility} visualizer-information-mobile-content d-flex flex-column`}
        >
          <Text className="mt-2 fw-semibold">
            {visualizerResults.projectName}
          </Text>

          <Switch
            label={swipeStateMobile === "post" ? "Post Event" : "Pre Event"}
            checked={swipeStateMobile === "post"}
            onChange={(e, data) =>
              setSwipeStateMobile(data.checked ? "post" : "pre")
            }
            className="mt-2"
          />

          <hr />
          {swipeStateMobile === "pre" ? (
            <>
              <Text className="fw-semibold">
                Pre disaster imagery
              </Text>
              <Text>
                {convertPreOrPostEventImageryDate(
                  visualizerResults.imageryCaptureDatePreEvent
                )}
              </Text>
              <Text size={200}>
                {convertPreOrPostEventImagerySource(
                  visualizerResults.preDisasterImagery?.url,
                  visualizerResults.sourceTypePreEvent
                )}
              </Text>
            </>
          ) : (
            <>
              <Text className="fw-semibold">
                Post disaster imagery
              </Text>
              <Text>
                {convertPreOrPostEventImageryDate(
                  visualizerResults.imageryCaptureDatePostEvent
                )}
              </Text>
              <Text size={200}>
                {convertPreOrPostEventImagerySource(
                  visualizerResults.postDisasterImagery?.url,
                  visualizerResults.sourceTypePostEvent
                )}
              </Text>
            </>
          )}
          <hr />

            {layerOptions.map((option) => (
              <Checkbox
                key={option.key}
                checked={!!layerVisibility[option.key]}
                disabled={option.disabled}
                label={option.label}
                onChange={(e, data) =>
                  onLayerVisibilityChange(option.key, data.checked)
                }
              />
            ))}
            <hr />
            <KeyboardShortcutHelp shortcuts={VISUALIZER_SHORTCUTS} />
        </div>

      </div>
    </>
  );
};

VisualizerInformationMobile.propTypes = {
  visualizerResults: PropType.object.isRequired,
  convertPreOrPostEventImageryDate: PropType.func.isRequired,
  convertPreOrPostEventImagerySource: PropType.func.isRequired,
  setSwipeStateMobile: PropType.func.isRequired,
  swipeStateMobile: PropType.string.isRequired,
  layerOptions: PropType.arrayOf(
    PropType.shape({
      key: PropType.string.isRequired,
      label: PropType.string.isRequired,
      disabled: PropType.bool,
    })
  ).isRequired,
  layerVisibility: PropType.object.isRequired,
  onLayerVisibilityChange: PropType.func.isRequired,
  surfaceClassName: PropType.string.isRequired,
};

export default VisualizerInformationMobile;
