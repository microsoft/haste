// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Slider,
  Button,
  Field,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

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
              <Field label="Opacity">
                <Slider
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateImageryProperties("opacity", data.value)}
                  value={imageryValues.opacity}
                />
              </Field>

              <Field label="Contrast">
                <Slider
                  min={-1}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateImageryProperties("contrast", data.value)}
                  value={imageryValues.contrast}
                />
              </Field>

              <Field label="Hue Rotation">
                <Slider
                  min={-180}
                  max={180}
                  step={1}
                  onChange={(e, data) => updateImageryProperties("hueRotation", data.value)}
                  value={imageryValues.hueRotation}
                />
              </Field>

              <Field label="Saturation">
                <Slider
                  min={-1}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateImageryProperties("saturation", data.value)}
                  value={imageryValues.saturation}
                />
              </Field>

              <Button
                appearance="transparent"
                icon={<FluentIcon name="Slider" />}
                className="w-100 mb-2 mt-2"
                onClick={resetImageryProperties}
              >
                Reset controls
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default VisualizerImageryControls;
