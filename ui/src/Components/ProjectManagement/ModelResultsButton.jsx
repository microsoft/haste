// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { PrimaryButton } from "@fluentui/react";
import React, { useContext, useState } from "react";
import PropTypes from "prop-types";
import { useNavigate } from "react-router-dom";
import { fileDownload } from "../../util/file";
import { AppContext } from "../../AppContext";
import ModelResultsStatusIndicator from "../OtherComponents/ModelResultsStatusIndicator";
import ValidationReportModal from "../BuildingValidation/ValidationReportModal";
import AssessmentReportModal from "../BuildingValidation/AssessmentReportModal";


function formatFileSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}


const ModelResultsButton = ({ model, projectId, imageLayerId, index, validationLabelCount }) => {
  ModelResultsButton.propTypes = {
    model: PropTypes.object.isRequired,
    projectId: PropTypes.string.isRequired,
    imageLayerId: PropTypes.string.isRequired,
    index: PropTypes.number.isRequired,
    validationLabelCount: PropTypes.number,
  };

  const { setDialog } = useContext(AppContext);
  const navigate = useNavigate();
  const [showValidationReport, setShowValidationReport] = useState(false);
  const [showAssessmentReport, setShowAssessmentReport] = useState(false);

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

  function handleDownload(url) {
    try {
      if (import.meta.env.VITE_STORAGE_APIM_URL) {
        url = url.replace(
          /^https?:\/\/[^/]+/,
          import.meta.env.VITE_STORAGE_APIM_URL
        );
      }
      fileDownload(url, setDialog);
    } catch (error) {
      setDialog({
        title: "Download Error",
        message: "An error occurred while downloading. Please try again later.",
        isOpen: true,
      });
    }
  }

  const trainingZipLabel = model.artifacts?.trainingZipSize
    ? `Download Training Artifacts (${formatFileSize(model.artifacts.trainingZipSize)})`
    : "Download Training Artifacts";

  const inferenceZipLabel = model.artifacts?.inferenceZipSize
    ? `Download Inference Artifacts (${formatFileSize(model.artifacts.inferenceZipSize)})`
    : "Download Inference Artifacts";

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
          handleDownload(model.gpkgUrl);
        },
        disabled: model.gpkgUrl === null || model.gpkgUrl === undefined || model.gpkgUrl === "",
      },
      {
        key: "downloadTrainingArtifacts",
        text: trainingZipLabel,
        iconProps: { iconName: "download" },
        onClick: () => {
          handleDownload(model.artifacts.trainingZipUrl);
        },
        disabled: !(model.artifacts?.trainingZipUrl),
      },
      {
        key: "downloadInferenceArtifacts",
        text: inferenceZipLabel,
        iconProps: { iconName: "download" },
        onClick: () => {
          handleDownload(model.artifacts.inferenceZipUrl);
        },
        disabled: !(model.artifacts?.inferenceZipUrl),
      },
      {
        key: "validationReport",
        text: "Validation Report",
        iconProps: { iconName: "ReportDocument" },
        disabled: model.inferenceStatus !== "Processed" || !(validationLabelCount > 0),
        onClick: () => setShowValidationReport(true),
      },
      {
        key: "assessmentReport",
        text: "Assessment Report",
        iconProps: { iconName: "AnalyticsReport" },
        // Predictions alone (+ cached footprints) are enough for the
        // damage-count estimate; labels are optional and just unlock the
        // precision/recall section inside the modal.
        disabled: model.inferenceStatus !== "Processed",
        onClick: () => setShowAssessmentReport(true),
      },
    ],
  });


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
        {showValidationReport && (
          <ValidationReportModal
            projectId={projectId}
            imageLayerId={imageLayerId}
            modelId={model.modelId}
            modelName={model.name}
            onDismiss={() => setShowValidationReport(false)}
          />
        )}
        {showAssessmentReport && (
          <AssessmentReportModal
            projectId={projectId}
            imageLayerId={imageLayerId}
            modelId={model.modelId}
            modelName={model.name}
            onDismiss={() => setShowAssessmentReport(false)}
          />
        )}
      </React.Fragment>
    );
  };

  export default ModelResultsButton;
