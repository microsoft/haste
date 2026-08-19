// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  Button,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import React, { useContext, useState } from "react";
import PropTypes from "prop-types";
import { useNavigate } from "react-router-dom";
import { fileDownload } from "../../util/file";
import { AppContext } from "../../AppContext";
import ModelResultsStatusIndicator from "../OtherComponents/ModelResultsStatusIndicator";
import ValidationReportModal from "../BuildingValidation/ValidationReportModal";
import AssessmentReportModal from "../BuildingValidation/AssessmentReportModal";
import PublishDatasetModal from "../PublishDatasetModal";


function formatFileSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}


const ModelResultsButton = ({ model, projectId, imageLayerId, index, validationLabelCount }) => {
  const { appParams, setDialog } = useContext(AppContext);
  const navigate = useNavigate();
  const [showValidationReport, setShowValidationReport] = useState(false);
  const [showAssessmentReport, setShowAssessmentReport] = useState(false);
  const [showPublishDataset, setShowPublishDataset] = useState(false);

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
    } catch {
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
        icon: <FluentIcon name="Forward" />,
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
        icon: <FluentIcon name="download" />,
        onClick: () => {
          handleDownload(model.gpkgUrl);
        },
        disabled: model.gpkgUrl === null || model.gpkgUrl === undefined || model.gpkgUrl === "",
      },
      {
        key: "downloadTrainingArtifacts",
        text: trainingZipLabel,
        icon: <FluentIcon name="download" />,
        onClick: () => {
          handleDownload(model.artifacts.trainingZipUrl);
        },
        disabled: !(model.artifacts?.trainingZipUrl),
      },
      {
        key: "downloadInferenceArtifacts",
        text: inferenceZipLabel,
        icon: <FluentIcon name="download" />,
        onClick: () => {
          handleDownload(model.artifacts.inferenceZipUrl);
        },
        disabled: !(model.artifacts?.inferenceZipUrl),
      },
      {
        key: "validationReport",
        text: "Validation Report",
        icon: <FluentIcon name="ReportDocument" />,
        disabled: model.inferenceStatus !== "Processed" || !(validationLabelCount > 0),
        onClick: () => setShowValidationReport(true),
      },
      {
        key: "assessmentReport",
        text: "Assessment Report",
        icon: <FluentIcon name="AnalyticsReport" />,
        // Predictions alone (+ cached footprints) are enough for the
        // damage-count estimate; labels are optional and just unlock the
        // precision/recall section inside the modal.
        disabled: model.inferenceStatus !== "Processed",
        onClick: () => setShowAssessmentReport(true),
      },
      ...(appParams.publishingEnabled
        ? [
            {
              key: "publishDataset",
              text: "Publish dataset…",
              icon: <FluentIcon name="Upload" />,
              disabled:
                model.inferenceStatus !== "Processed" || !model.gpkgUrl,
              onClick: () => setShowPublishDataset(true),
            },
          ]
        : []),
    ],
  });


    return (
      <React.Fragment key={"models_" + projectId + "_" + imageLayerId}>
        <div className="d-flex align-items-center pt-1 pb-1">
          <Menu positioning="below-end">
            <MenuTrigger disableButtonEnhancement>
              <Button
                appearance="primary"
                id={"singleModelResults" + index}
                className="dashboard-button dashboard-button-light"
                disabled={evaluateViewResultsButtonState(model)}
              >
                Results
              </Button>
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                {resultsMenuOptions(model).items.map((mi) => (
                  <MenuItem
                    key={mi.key}
                    icon={mi.icon}
                    disabled={mi.disabled}
                    onClick={mi.onClick}
                  >
                    {mi.text}
                  </MenuItem>
                ))}
              </MenuList>
            </MenuPopover>
          </Menu>
          {model.artifacts && model.artifacts.zipStatusMessage && (
            <ModelResultsStatusIndicator
              statusMessage={model.artifacts.zipStatusMessage}
              contextLabel={`Model: ${model.name} \u00b7 Results`}
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
        {showPublishDataset && (
          <PublishDatasetModal
            projectId={projectId}
            imageLayerId={imageLayerId}
            modelId={model.modelId}
            onDismiss={() => setShowPublishDataset(false)}
            onStarted={() =>
              setDialog(
                "Publishing started",
                "Track progress in Published Datasets.",
              )
            }
          />
        )}
      </React.Fragment>
    );
  };

ModelResultsButton.propTypes = {
  model: PropTypes.object.isRequired,
  projectId: PropTypes.string.isRequired,
  imageLayerId: PropTypes.string.isRequired,
  index: PropTypes.number.isRequired,
  validationLabelCount: PropTypes.number,
};

  export default ModelResultsButton;
