// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Checkbox,
  Button,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import { useState, useContext } from "react";
import PropType from "prop-types";
import { AppContext } from "../../AppContext";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { VISUALIZER_SHORTCUTS } from "../keyboardShortcuts";

const DAMAGE_LEGEND = [
  { label: "0 - 20% damaged", color: "#FFFFFF" },
  { label: "20 - 40% damaged", color: "#FFB99F" },
  { label: "40 - 60% damaged", color: "#FF6846" },
  { label: "60 - 80% damaged", color: "#DD1E25" },
  { label: "80 - 100% damaged", color: "#85000F" },
];

const useStyles = makeStyles({
  legend: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
    marginTop: tokens.spacingVerticalM,
    marginBottom: tokens.spacingVerticalM,
  },
  legendItem: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    color: tokens.colorNeutralForeground1,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    whiteSpace: "nowrap",
  },
  legendSwatch: {
    width: "28px",
    height: "18px",
    flex: "0 0 28px",
    boxSizing: "border-box",
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusSmall,
  },
});

const InfoPanel = ({
  togglePredictedDamageLayerVisibility,
  resetMapPosition,
  visualizerResults,
  surfaceClassName,
}) => {
  const styles = useStyles();
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
        className={`absolute-labels info-panel col-12 ${surfaceClassName}`}
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

            <div className={styles.legend} aria-label="Damage percentage legend">
              {DAMAGE_LEGEND.map((item) => (
                <div className={styles.legendItem} key={item.label}>
                  <span
                    className={styles.legendSwatch}
                    style={{ backgroundColor: item.color }}
                    aria-hidden="true"
                  />
                  <span>{item.label}</span>
                </div>
              ))}
            </div>

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

            <KeyboardShortcutHelp shortcuts={VISUALIZER_SHORTCUTS} />
          </div>
        </div>
      </div>
    </>
  );
};

InfoPanel.propTypes = {
  togglePredictedDamageLayerVisibility: PropType.func.isRequired,
  resetMapPosition: PropType.func.isRequired,
  visualizerResults: PropType.object.isRequired,
  surfaceClassName: PropType.string.isRequired,
};

export default InfoPanel;
