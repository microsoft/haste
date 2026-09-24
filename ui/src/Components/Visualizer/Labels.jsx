// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Dependencies 
import { Button, Text, Link, makeStyles, tokens } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { useNavigate } from "react-router-dom";
import { convertDateToString } from "../../util/conversion";
import {
  sourceTypeOptions,
  normalizeSourceTypeKey,
} from "../CreateEditImageLayerHelper";
import { safeHref } from "../../util/validation";
import "../../assets/css/labels.css";
import PropType from "prop-types";
import InfoPanel from "./InfoPanel";
import VisualizerInformationMobile from "./VisualizerInformationMobile";
import { hasRasterLayer } from "./predictionResults.js";
import { swipeLeftPaneLabel, swipeRightPaneLabel } from "./visualizerSwipe.js";
import "../../assets/css/drawingToolbar.css";

const useStyles = makeStyles({
  surface: {
    color: tokens.colorNeutralForeground1,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow8,
  },
});

const Labels = ({
  layerOptions,
  layerVisibility,
  onLayerVisibilityChange,
  resetMapPosition,
  visualizerResults,
  setSwipeStateMobile,
  swipeStateMobile
}) => {
  const navigate = useNavigate();
  const styles = useStyles();

  const handleBackNavigation = () => {
    navigate(-1);
  };


  // Function to convert the source type to a string with a link if applicable
  function convertPreOrPostEventImagerySource(imageryUrl, sourceType) {
    var sourceTypeTemp = "";

    if (!imageryUrl || imageryUrl === "") {
      sourceTypeTemp = "azure_maps";
    }else{
      sourceTypeTemp = sourceType;
    }

    const sourceTypeTempObject = sourceTypeOptions.find(
      (option) => option.key === normalizeSourceTypeKey(sourceTypeTemp)
    ) || null;

    if (!sourceTypeTempObject) return "Source: Unknown";
    if (sourceTypeTempObject.url === ""){
      return "Source: " + sourceTypeTempObject.visualizerText;
    }else{
      return (
        <Link href={safeHref(sourceTypeTempObject.url)} target="_blank" rel="noopener noreferrer">
          Source: {sourceTypeTempObject.visualizerText}
        </Link>
      );
    }
  }

  // Function to convert the date to a string format
  function convertPreOrPostEventImageryDate(date) {
    if(!date || date === "") {
      return "--";
    }
    return convertDateToString(date);
  }

  return (
    <>
      <div className="labeling-tool-surface labeling-navigation-controls">
        <Button
          appearance="transparent"
          id="visualizerBackButton"
          icon={<FluentIcon name="ChevronLeft" />}
          onClick={handleBackNavigation}
        >
          Back
        </Button>
      </div>
      {visualizerResults.projectName && (
        <>
          {/* PRE DISASTER */}

          <div className={`absolute-labels pre-disaster d-flex flex-column d-none d-lg-flex ${styles.surface}`}>
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
          </div>

          {/* POST DISASTER */}

          <div className={`absolute-labels post-disaster d-flex flex-column d-none d-lg-flex ${styles.surface}`}>
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
          </div>
        
          
          {/* CONTROLS AND AND INFOPANEL */}

          <VisualizerInformationMobile
            visualizerResults={visualizerResults}
            convertPreOrPostEventImageryDate={convertPreOrPostEventImageryDate}
            convertPreOrPostEventImagerySource={convertPreOrPostEventImagerySource}
            setSwipeStateMobile={setSwipeStateMobile}
            swipeStateMobile={swipeStateMobile}
            layerOptions={layerOptions}
            layerVisibility={layerVisibility}
            onLayerVisibilityChange={onLayerVisibilityChange}
            surfaceClassName={styles.surface}
          />

          <InfoPanel
            layerOptions={layerOptions}
            layerVisibility={layerVisibility}
            onLayerVisibilityChange={onLayerVisibilityChange}
            resetMapPosition={resetMapPosition}
            visualizerResults={visualizerResults}
            surfaceClassName={styles.surface}
          />
        </>
      )}
    </>
  );
};

Labels.propTypes = {
  layerOptions: PropType.array.isRequired,
  layerVisibility: PropType.object.isRequired,
  onLayerVisibilityChange: PropType.func.isRequired,
  resetMapPosition: PropType.func.isRequired,
  visualizerResults: PropType.object.isRequired,
  setSwipeStateMobile: PropType.func.isRequired,
  swipeStateMobile: PropType.string.isRequired,
};

export default Labels;
