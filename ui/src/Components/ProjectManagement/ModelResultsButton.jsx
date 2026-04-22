// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { PrimaryButton } from "@fluentui/react";
import React, { useContext } from "react";
import PropTypes from "prop-types";
import { useNavigate } from "react-router-dom";
import { fileDownload } from "../../util/file";
import { AppContext } from "../../AppContext";
import ModelResultsStatusIndicator from "../OtherComponents/ModelResultsStatusIndicator";



const ModelResultsButton = ({ model, projectId, imageLayerId, index }) => {
  ModelResultsButton.propTypes = {
    model: PropTypes.object.isRequired,
    projectId: PropTypes.string.isRequired,
    imageLayerId: PropTypes.string.isRequired,
    index: PropTypes.number.isRequired,
  };

  const { setDialog } = useContext(AppContext);
  const navigate = useNavigate();

  function evaluateViewResultsButtonState(model) {
    // Results button must be enabled if inference jobs exist and status is processed
    if (
      model.inferenceJobs.length > 0 &&
      model.inferenceStatus === "Processed"
    ) {
      return false;
    // If inference fails, then the button should be enabled because will allow the user to download the artifacts when they are ready.
    } else if (model.status === "Failed" && model.artifacts != null) {
      return false;
    }
    return true;
  }

  const resultsMenuOptions = (model) => ({
    items: [
      {
        disabled: model.inferenceStatus !== "Processed",
        key: "viewResults",
        text: "View",
        iconProps: { iconName: "Forward" },
        onClick: () => {
          navigate(
            "/visualizer/" +
            projectId +
            "/" +
            imageLayerId +
            "/" +
            model.modelId
          );
        },
      },
      {
        key: "downloadGeopackage",
        text: "Download Geopackage (.gpkg)",
        iconProps: { iconName: "download" },
        onClick: () => {
          handleGeopackageDownload(model);
        },
        disabled: model.gpkgUrl === null || model.gpkgUrl === undefined || model.gpkgUrl === "",
      },
      {
        key: "downloadAllArtifacts",
        text: "Download All Artifacts",
        iconProps: { iconName: "download" },
        onClick: () => {
          handleArtifactsDownload(model);
        },
        disabled: !(model.artifacts && model.artifacts.zipUrl),
      },
    ],
  });


  function handleGeopackageDownload(model) {
    try {
      if (import.meta.env.VITE_STORAGE_APIM_URL) {
        model.gpkgUrl = model.gpkgUrl.replace(
          /^https?:\/\/[^/]+/,
          import.meta.env.VITE_STORAGE_APIM_URL
        );
      }
      fileDownload(model.gpkgUrl, setDialog);
    } catch (error) {
      setDialog({
        title: "Download Error",
        message: "An error occurred while downloading the GeoPackage.",
        isOpen: true,
      });
    }
  }

    function handleArtifactsDownload(model) {
      try {
        if (import.meta.env.VITE_STORAGE_APIM_URL) {
          model.artifacts.zipUrl = model.artifacts.zipUrl.replace(
            /^https?:\/\/[^/]+/,
            import.meta.env.VITE_STORAGE_APIM_URL
          );
        }
        fileDownload(model.artifacts.zipUrl, setDialog);
      } catch (error) {
        setDialog({
          title: "Download Error",
          message: "An error occurred while downloading artifacts.",
          isOpen: true,
        });
      }
    }

    return (
      <React.Fragment key={"models_" + projectId + "_" + imageLayerId}>
        <div className="d-flex align-items-center pt-1 pb-1">
          <PrimaryButton
            id={"singleModelResults" + index}
            text="Results"
            menuProps={resultsMenuOptions(model)}
            allowDisabledFocus
            className="dashboard-button"
            disabled={evaluateViewResultsButtonState(model)}
          />
          {model.artifacts && model.artifacts.zipStatusMessage && (
            <ModelResultsStatusIndicator
              statusMessage={model.artifacts.zipStatusMessage}
            />
          )}
        </div>
      </React.Fragment>
    );
  };

  export default ModelResultsButton;
