// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
  Slider,
  Button,
  Field,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";

import PropTypes from "prop-types";

const useStyles = makeStyles({
  surface: {
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow8,
  },
});

const VisualizerImageryControls = ({ updateImageryProperties, resetImageryProperties, imageryValues,  visualizerResults}) => {
  const styles = useStyles();

  return (
    <>
      {visualizerResults.projectName && (
        <div

          className={`d-none d-lg-flex absolute-labels imagery-controls ${styles.surface}`}
          id="imageryControls"
        >
          <div>
            <div
              style={{
                paddingTop: "5px",
              }}
              className="d-none d-lg-block"
            >
              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Opacity</span>
                    <output>{Math.round(imageryValues.opacity * 100)}%</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateImageryProperties("opacity", data.value)}
                  value={imageryValues.opacity}
                />
              </Field>

              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Contrast</span>
                    <output>{imageryValues.contrast.toFixed(2)}</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
                  min={-1}
                  max={1}
                  step={0.01}
                  onChange={(e, data) => updateImageryProperties("contrast", data.value)}
                  value={imageryValues.contrast}
                />
              </Field>

              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Hue Rotation</span>
                    <output>{imageryValues.hueRotation}&deg;</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
                  min={-180}
                  max={180}
                  step={1}
                  onChange={(e, data) => updateImageryProperties("hueRotation", data.value)}
                  value={imageryValues.hueRotation}
                />
              </Field>

              <Field
                className="labeling-imagery-field"
                label={
                  <span className="labeling-imagery-label">
                    <span>Saturation</span>
                    <output>{imageryValues.saturation.toFixed(2)}</output>
                  </span>
                }
              >
                <Slider
                  className="labeling-imagery-slider"
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

VisualizerImageryControls.propTypes = {
  updateImageryProperties: PropTypes.func.isRequired,
  resetImageryProperties: PropTypes.func.isRequired,
  imageryValues: PropTypes.object.isRequired,
  visualizerResults: PropTypes.object.isRequired,
};

export default VisualizerImageryControls;
