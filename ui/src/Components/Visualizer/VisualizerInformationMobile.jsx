// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Checkbox,
  Button,
  Text,
  Switch,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";


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
        <Button
          appearance="transparent"
          icon={<FluentIcon name={panelVisibility === "" ? "cancel" : "info"} />}
          onClick={() => {
            togglePanelVisibility();
          }}
        >
          <span className="ms-2 fw-semibold">Info</span>
        </Button>

        <div className={panelVisibility + " p-3 pt-0 d-flex flex-column"}>
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
                  visualizerResults.preDisasterImagery.url, visualizerResults.sourceTypePreEvent
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
                  visualizerResults.postDisasterImagery.url, visualizerResults.sourceTypePostEvent
                )}
              </Text>
            </>
          )}
          <hr />


            <Checkbox
              defaultChecked={true}
              label="Predicted damage layer"
              onChange={(e, data) =>
                togglePredictedDamageLayerVisibility(
                  "predictedDamageLayer",
                  data.checked
                )
              }
            />
            <Checkbox
              defaultChecked={false}
              label="Predictions layer (raw)"
              onChange={(e, data) =>
                togglePredictedDamageLayerVisibility(
                  "predictionsLayer",
                  data.checked
                )
              }
            />
        </div>

      </div>
    </>
  );
};

export default VisualizerInformationMobile;
