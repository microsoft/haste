// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Slider,
  ActionButton,
} from "@fluentui/react";

import PropTypes from "prop-types";
import { useState, useEffect, useRef } from "react";

const VisualizerImageryControls = ({ updateImageryProperties, resetImageryProperties, imageryValues,  visualizerResults}) => {
  VisualizerImageryControls.propTypes = {
    updateImageryProperties: PropTypes.func.isRequired,
    resetImageryProperties: PropTypes.func.isRequired,
    imageryValues: PropTypes.object.isRequired,
  };


  return (
    <>
      {visualizerResults.projectName && (
        <div

          className=" d-none d-lg-flex absolute-labels imagery-controls"
          id="imageryControls"
        >
          <div>
            <div
              style={{
                paddingTop: "5px",
              }}
              className="d-none d-lg-block"
            >
              <Slider
                label="Opacity"
                min={0}
                max={1}
                step={0.01}
                showValue={false}
                onChange={(value) => updateImageryProperties("opacity", value)}
                value={imageryValues.opacity}
              />

              <Slider
                label="Contrast"
                min={-1}
                max={1}
                step={0.01}
                showValue={false}
                onChange={(value) => updateImageryProperties("contrast", value)}
                value={imageryValues.contrast}
              />

              <Slider
                label="Hue Rotation"
                min={-180}
                max={180}
                step={1}
                showValue={false}
                onChange={(value) => updateImageryProperties("hueRotation", value)}
                value={imageryValues.hueRotation}
              />

              <Slider
                label="Saturation"
                min={-1}
                max={1}
                step={0.01}
                showValue={false}
                onChange={(value) => updateImageryProperties("saturation", value)}
                value={imageryValues.saturation}
              />

              <ActionButton
                iconProps={{ iconName: "Slider" }}
                className="w-100 mb-2 mt-2"
                onClick={resetImageryProperties}
              >
                Reset controls
              </ActionButton>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default VisualizerImageryControls;
