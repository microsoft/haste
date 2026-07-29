// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Checkbox,
  Button,
  Text,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import { useState, useContext } from "react";
import PropType from "prop-types";
import { AppContext } from "../../AppContext";

const InfoPanel = ({
  togglePredictedDamageLayerVisibility,
  resetMapPosition,
  visualizerResults,
}) => {
  InfoPanel.propTypes = {
    togglePredictedDamageLayerVisibility: PropType.func.isRequired,
    resetMapPosition: PropType.func.isRequired,
    visualizerResults: PropType.object.isRequired,
  };

  const [panelVisibility, setPanelVisibility] = useState("");
  const { appParams } = useContext(AppContext);

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
        className="absolute-labels info-panel col-12"
      >
        <Button
          appearance="transparent"
          icon={<FluentIcon name={panelVisibility === "" ? "chevronDown" : "chevronUp"} />}
          onClick={() => {
            togglePanelVisibility();
          }}
        >
          <span className="ms-2 fw-semibold">{appParams.bootstrapBreakpoint > 0 ? "Map Settings" : "Legend"}</span>
        </Button>

        <div className={panelVisibility + " ps-3 pe-3"}>


          <div className="d-flex flex-column">
            <Text size={200} className="fw-bold mt-3 mb-3 d-none">
              Select Imagery Layers
            </Text>
            <div
              className="mt-3 info-panel-checkboxes-wrapper d-none d-xl-flex flex-column"
            >
              <Checkbox
                defaultChecked={true}
                label="Predicted building damage layer"
                onChange={(e, data) =>
                  togglePredictedDamageLayerVisibility(
                    "predictedDamageLayer",
                    data.checked
                  )
                }
              />
              <Checkbox
                className="mt-2"
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
          <div className="d-flex flex-column">
            <Text size={200} className="fw-bold mt-2 d-none d-xl-block">
              Legend
            </Text>

            <img
              src="../../../assets/img/visualizerLegend.png"
              alt="legend"
              className="map-legend mb-3 mt-3"
            />

            <Button
              appearance="transparent"
              icon={<FluentIcon name="MapPin" />}
              className="d-none d-xl-block"
              onClick={() => {
                resetMapPosition(visualizerResults.studyArea);
              }}
            >
              Reset map position
            </Button>

          </div>
        </div>
      </div>
    </>
  );
};

export default InfoPanel;
