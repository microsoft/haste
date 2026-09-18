// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Checkbox,
  Button,
  Text,
  Switch,
  makeStyles,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";


import { useState } from "react";
import PropType from "prop-types";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { VISUALIZER_SHORTCUTS } from "../keyboardShortcuts";
import PredictionLegend from "./PredictionLegend";
import { hasRasterLayer } from "./predictionResults.js";
import { RESULTS_DESKTOP_MIN_WIDTH, swipeLeftPaneLabel, swipeRightPaneLabel } from "./visualizerSwipe.js";

const useStyles = makeStyles({
  panel: {
    zIndex: 1000,
    display: "block",
    [`@media (min-width: ${RESULTS_DESKTOP_MIN_WIDTH}px)`]: { display: "none" },
  },
  scroll: { maxHeight: "calc(100vh - 180px)", overflowY: "auto", overscrollBehavior: "contain" },
});

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
  const styles = useStyles();

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
        } ${surfaceClassName} ${styles.panel}`}
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
          className={`${panelVisibility} visualizer-information-mobile-content d-flex flex-column ${styles.scroll}`}
        >
          <Text className="mt-2 fw-semibold">
            {visualizerResults.projectName}
          </Text>

          <Switch
            label={swipeStateMobile === "post" ? swipeRightPaneLabel(visualizerResults) : swipeLeftPaneLabel(visualizerResults)}
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
                {swipeLeftPaneLabel(visualizerResults)}
              </Text>
              <Text>
                {convertPreOrPostEventImageryDate(
                  visualizerResults.imageryCaptureDatePreEvent
                )}
              </Text>
              <Text size={200}>
                {convertPreOrPostEventImagerySource(
                  hasRasterLayer(visualizerResults.preDisasterImagery) ? visualizerResults.preDisasterImagery.url : "",
                  visualizerResults.sourceTypePreEvent
                )}
              </Text>
            </>
          ) : (
            <>
              <Text className="fw-semibold">
                {swipeRightPaneLabel(visualizerResults)}
              </Text>
              <Text>
                {convertPreOrPostEventImageryDate(
                  visualizerResults.imageryCaptureDatePostEvent
                )}
              </Text>
              <Text size={200}>
                {convertPreOrPostEventImagerySource(
                  hasRasterLayer(visualizerResults.postDisasterImagery) ? visualizerResults.postDisasterImagery.url : "",
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
                onChange={(_event, data) => onLayerVisibilityChange(option.key, data.checked)}
              />
            ))}
            {layerVisibility.footprints && <PredictionLegend />}
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
  layerOptions: PropType.array.isRequired,
  layerVisibility: PropType.object.isRequired,
  onLayerVisibilityChange: PropType.func.isRequired,
  surfaceClassName: PropType.string.isRequired,
};

export default VisualizerInformationMobile;
