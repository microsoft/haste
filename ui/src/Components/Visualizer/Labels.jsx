// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Dependencies 
import { ActionButton, Text, Link, Toggle } from "@fluentui/react";
import { useNavigate } from "react-router-dom";
import { convertDateToString } from "../../util/conversion";
import { sourceTypeOptions } from "../CreateEditImageLayerHelper";
import "../../assets/css/labels.css";
import PropType from "prop-types";
import InfoPanel from "./InfoPanel";
import VisualizerInformationMobile from "./VisualizerInformationMobile";

const Labels = ({
  togglePredictedDamageLayerVisibility,
  resetMapPosition,
  visualizerResults,
  setSwipeStateMobile,
  swipeStateMobile
}) => {
  Labels.propTypes = {
    togglePredictedDamageLayerVisibility: PropType.func.isRequired,
    resetMapPosition: PropType.func.isRequired,
    visualizerResults: PropType.object.isRequired,
    setSwipeStateMobile: PropType.func.isRequired,
    swipeStateMobile: PropType.string.isRequired,
  };

  const navigate = useNavigate();

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
      (option) => option.key === sourceTypeTemp
    ) || null;

    if (!sourceType || sourceType === "" || !sourceTypeTempObject) return "Source: Unknown";
    if (sourceTypeTempObject.url === ""){
      return "Source: " + sourceTypeTempObject.visualizerText;
    }else{
      return (
        <Link href={sourceTypeTempObject.url} target="_blank">
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
          {/* PRE DISASTER */}

          <div className="absolute-labels pre-disaster d-flex flex-column labels-back-button">
            <ActionButton
              id="visualizerBackButton"
              iconProps={{ iconName: "ChevronLeft" }}
              className="w-100 p-0 m-0"
              onClick={handleBackNavigation}
            >
              Back
            </ActionButton>
          </div>

          <div className="absolute-labels pre-disaster d-flex flex-column d-none d-lg-flex">
            <Text variant="large" className="fw-semibold">
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
          </div>

          {/* POST DISASTER */}

          <div className="absolute-labels post-disaster d-flex flex-column d-none d-lg-flex">
            <Text variant="large" className="fw-semibold">
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
          </div>
        
          
          {/* CONTROLS AND AND INFOPANEL */}

          <VisualizerInformationMobile
            visualizerResults={visualizerResults}
            convertPreOrPostEventImageryDate={convertPreOrPostEventImageryDate}
            convertPreOrPostEventImagerySource={convertPreOrPostEventImagerySource}
            setSwipeStateMobile={setSwipeStateMobile}
            swipeStateMobile={swipeStateMobile}
            togglePredictedDamageLayerVisibility={
              togglePredictedDamageLayerVisibility
            }
          />

          <InfoPanel
            togglePredictedDamageLayerVisibility={
              togglePredictedDamageLayerVisibility
            }
            resetMapPosition={resetMapPosition}
            visualizerResults={visualizerResults}
          />
        </>
      )}
    </>
  );
};

export default Labels;
