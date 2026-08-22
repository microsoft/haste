// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// The results page's map-settings card: which layers are drawn, what their
// colours mean, and the shortcuts that drive the view.
//
// The layer list is NOT fixed. An inference model has pre-coloured damage
// rasters to toggle; an embedding model has none, and offering a checkbox for
// a layer that was never added to the map is worse than offering nothing at
// all. So the rows come from visualizerLayerOptions() — pure and unit-tested —
// and the legends follow whatever is actually on screen.
import {
  Checkbox,
  Button,
  Text,
  Tooltip,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import { useState, useContext } from "react";
import PropType from "prop-types";
import { AppContext } from "../../AppContext";
import KeyboardShortcutHelp from "../KeyboardShortcutHelp";
import { VISUALIZER_SHORTCUTS } from "../keyboardShortcuts";

// The damage raster is baked server-side into these five bands, so this
// legend is only meaningful when that raster exists.
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
  // The footprint swatches use the same theme tokens the map paint
  // expressions resolve, so the legend cannot drift from the map.
  damagedSwatch: {
    backgroundColor: tokens.colorStatusDangerBackground3,
  },
  notDamagedSwatch: {
    backgroundColor: tokens.colorStatusSuccessBackground3,
  },
  unknownSwatch: {
    backgroundColor: tokens.colorNeutralForeground3,
  },
  pendingSwatch: {
    backgroundColor: tokens.colorNeutralBackground5,
  },
});

const InfoPanel = ({
  layerOptions,
  layerVisibility,
  onLayerVisibilityChange,
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

  const hasDamageRaster = layerOptions.some(
    (option) => option.key === "predictedDamageLayer"
  );
  const footprintOption = layerOptions.find(
    (option) => option.key === "footprints"
  );
  const showFootprintLegend = !!footprintOption && !footprintOption.disabled;

  const footprintLegend = [
    { label: "Predicted damaged", className: styles.damagedSwatch },
    { label: "Predicted not damaged", className: styles.notDamagedSwatch },
    { label: "Unknown / uncertain", className: styles.unknownSwatch },
    { label: "Not yet classified", className: styles.pendingSwatch },
  ];

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
              {layerOptions.map((option) => {
                const checkbox = (
                  <Checkbox
                    key={option.key}
                    checked={!!layerVisibility[option.key]}
                    disabled={option.disabled}
                    label={option.label}
                    onChange={(e, data) =>
                      onLayerVisibilityChange(option.key, data.checked)
                    }
                  />
                );
                // A disabled Fluent control swallows pointer events, so the
                // tooltip goes on a wrapper rather than the checkbox.
                return option.disabled ? (
                  <Tooltip
                    key={option.key}
                    content="This layer is still being prepared"
                    relationship="label"
                  >
                    <div>{checkbox}</div>
                  </Tooltip>
                ) : (
                  checkbox
                );
              })}
            </div>
          </div>
          <div className="d-flex flex-column">
            <Text size={200} className="fw-bold mt-2 d-none d-xl-block">
              Legend
            </Text>

            {hasDamageRaster && (
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
            )}

            {showFootprintLegend && (
              <div className={styles.legend} aria-label="Predicted building legend">
                {footprintLegend.map((item) => (
                  <div className={styles.legendItem} key={item.label}>
                    <span
                      className={`${styles.legendSwatch} ${item.className}`}
                      aria-hidden="true"
                    />
                    <span>{item.label}</span>
                  </div>
                ))}
              </div>
            )}

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
  layerOptions: PropType.arrayOf(
    PropType.shape({
      key: PropType.string.isRequired,
      label: PropType.string.isRequired,
      disabled: PropType.bool,
    })
  ).isRequired,
  layerVisibility: PropType.object.isRequired,
  onLayerVisibilityChange: PropType.func.isRequired,
  resetMapPosition: PropType.func.isRequired,
  visualizerResults: PropType.object.isRequired,
  surfaceClassName: PropType.string.isRequired,
};

export default InfoPanel;
