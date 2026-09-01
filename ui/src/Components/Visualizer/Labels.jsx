// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// The overlay chrome on the results page: navigation, the pre/post imagery
// provenance blocks, and the map-settings panel (in its desktop and mobile
// forms).
//
// It also carries the edit affordance. Prediction editing is a MODE of this
// page rather than a screen of its own — the analyst keeps the same two maps,
// the same swipe divider and the same footprints, and simply gains the
// ability to click them — so the pencil sits next to Back, and entering edit
// mode swaps the read-only panels for the edit panel the Visualizer renders.
// Dependencies 
import { Button, Text, Link, Tooltip, makeStyles, tokens } from "@fluentui/react-components";
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
  resetMapPosition,
  visualizerResults,
  setSwipeStateMobile,
  swipeStateMobile,
  layerOptions,
  layerVisibility,
  onLayerVisibilityChange,
  isEditMode,
  canEdit,
  editTooltip,
  onToggleEditMode,
  navigationControlsClassName = "",
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

    if (!sourceType || sourceType === "" || !sourceTypeTempObject) return "Source: Unknown";
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
      {visualizerResults.projectName && (
        <>
          {/* NAVIGATION AND EDIT MODE */}

          <div
            className={`labeling-tool-surface labeling-navigation-controls ${navigationControlsClassName}`}
          >
            <Button
              appearance="transparent"
              id="visualizerBackButton"
              icon={<FluentIcon name="ChevronLeft" />}
              onClick={handleBackNavigation}
              disabled={isEditMode}
            >
              Back
            </Button>
            <Tooltip
              content={
                isEditMode
                  ? "Leave edit mode and go back to the read-only results"
                  : editTooltip
              }
              relationship="label"
            >
              <Button
                appearance={isEditMode ? "primary" : "transparent"}
                id="visualizerEditButton"
                icon={<FluentIcon name={isEditMode ? "checkmark" : "edit"} />}
                // A disabled Fluent button drops out of the tab order and
                // swallows its own tooltip, which is exactly where the reason
                // for the disabled state lives.
                disabledFocusable={!isEditMode && !canEdit}
                onClick={onToggleEditMode}
              >
                {isEditMode ? "Done" : "Edit"}
              </Button>
            </Tooltip>
          </div>

          {/* PRE DISASTER */}

          <div className={`absolute-labels pre-disaster d-flex flex-column d-none d-lg-flex ${styles.surface}`}>
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
                visualizerResults.preDisasterImagery?.url,
                visualizerResults.sourceTypePreEvent
              )}
            </Text>
          </div>

          {/* POST DISASTER */}
          {/* Top-right, where the edit panel goes: it steps aside in edit mode. */}

          {!isEditMode && (
            <div className={`absolute-labels post-disaster d-flex flex-column d-none d-lg-flex ${styles.surface}`}>
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
                  visualizerResults.postDisasterImagery?.url,
                  visualizerResults.sourceTypePostEvent
                )}
              </Text>
            </div>
          )}
        
          
          {/* CONTROLS AND AND INFOPANEL */}
          {/* Both are read-only views of the layers; the edit panel replaces
              them so the two never fight for the same corner. */}

          {!isEditMode && (
            <>
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
      )}
    </>
  );
};

Labels.propTypes = {
  resetMapPosition: PropType.func.isRequired,
  visualizerResults: PropType.object.isRequired,
  setSwipeStateMobile: PropType.func.isRequired,
  swipeStateMobile: PropType.string.isRequired,
  layerOptions: PropType.array.isRequired,
  layerVisibility: PropType.object.isRequired,
  onLayerVisibilityChange: PropType.func.isRequired,
  isEditMode: PropType.bool.isRequired,
  canEdit: PropType.bool.isRequired,
  editTooltip: PropType.string.isRequired,
  onToggleEditMode: PropType.func.isRequired,
  navigationControlsClassName: PropType.string,
};

export default Labels;
