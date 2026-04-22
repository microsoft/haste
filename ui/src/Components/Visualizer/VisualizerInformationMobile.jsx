// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Checkbox,
  ActionButton,
  Text,
  Toggle,
} from "@fluentui/react";


import { useState } from "react";
import PropType from "prop-types";

const VisualizerInformationMobile = ({
  visualizerResults,
  convertPreOrPostEventImageryDate,
  convertPreOrPostEventImagerySource,
  setSwipeStateMobile,
  swipeStateMobile,
  togglePredictedDamageLayerVisibility
}) => {
  VisualizerInformationMobile.propTypes = {
    visualizerResults: PropType.object.isRequired,
    convertPreOrPostEventImageryDate: PropType.func.isRequired,
    convertPreOrPostEventImagerySource: PropType.func.isRequired,
    setSwipeStateMobile: PropType.func.isRequired,
    swipeStateMobile: PropType.string.isRequired,
    togglePredictedDamageLayerVisibility: PropType.func.isRequired,
  };

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
        className="absolute-labels post-disaster visualizer-information-mobile d-block d-lg-none"
      >
        <ActionButton
          iconProps={{ iconName: panelVisibility === "" ? "cancel" : "info" }}
          onClick={() => {
            togglePanelVisibility();
          }}
        >
          <span className="ms-2 fw-semibold">Info</span>
        </ActionButton>

        <div className={panelVisibility + " p-3 pt-0 d-flex flex-column"}>
          <Text variant="medium" className="mt-2 fw-semibold">
            {visualizerResults.projectName}
          </Text>

          <Toggle
            onText="Post Event"
            offText="Pre Event"
            checked={swipeStateMobile === "post"}
            onChange={(e, checked) =>
              setSwipeStateMobile(checked ? "post" : "pre")
            }
            className="mt-2"
          />

          <hr />
          {swipeStateMobile === "pre" ? (
            <>
              <Text variant="medium" className="fw-semibold">
                Pre disaster imagery
              </Text>
              <Text variant="medium">
                {convertPreOrPostEventImageryDate(
                  visualizerResults.imageryCaptureDatePreEvent
                )}
              </Text>
              <Text variant="small">
                {convertPreOrPostEventImagerySource(
                  visualizerResults.preDisasterImagery.url, visualizerResults.sourceTypePreEvent
                )}
              </Text>
            </>
          ) : (
            <>
              <Text variant="medium" className="fw-semibold">
                Post disaster imagery
              </Text>
              <Text variant="medium">
                {convertPreOrPostEventImageryDate(
                  visualizerResults.imageryCaptureDatePostEvent
                )}
              </Text>
              <Text variant="small">
                {convertPreOrPostEventImagerySource(
                  visualizerResults.postDisasterImagery.url, visualizerResults.sourceTypePostEvent
                )}
              </Text>
            </>
          )}
          <hr />


            <Checkbox
              defaultChecked={true}
              label="Predicted damage layer"
              onChange={(e, checked) =>
                togglePredictedDamageLayerVisibility(
                  "predictedDamageLayer",
                  checked
                )
              }
            />
        </div>

      </div>
    </>
  );
};

export default VisualizerInformationMobile;
