// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext } from "react";
import PropTypes from "prop-types";
import { fileDownload } from "../../util/file";
import { AppContext } from "../../AppContext";
import ModelResultsStatusIndicator from "../OtherComponents/ModelResultsStatusIndicator";
import ModelResultsMenu from "./ModelResultsMenu";

function formatFileSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

const ModelResultsButton = ({ model, projectId, imageLayerId, index, validationLabelCount }) => {
  const { setDialog } = useContext(AppContext);

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

  const artifactItems = [
    {
      key: "downloadTrainingArtifacts",
      text: model.artifacts?.trainingZipSize
        ? `Download Training Artifacts (${formatFileSize(model.artifacts.trainingZipSize)})`
        : "Download Training Artifacts",
      icon: "download",
      onClick: () => handleDownload(model.artifacts.trainingZipUrl),
      disabled: !model.artifacts?.trainingZipUrl,
    },
    {
      key: "downloadInferenceArtifacts",
      text: model.artifacts?.inferenceZipSize
        ? `Download Inference Artifacts (${formatFileSize(model.artifacts.inferenceZipSize)})`
        : "Download Inference Artifacts",
      icon: "download",
      onClick: () => handleDownload(model.artifacts.inferenceZipUrl),
      disabled: !model.artifacts?.inferenceZipUrl,
    },
  ];

  return (
    <div className="d-flex align-items-center pt-1 pb-1">
      <ModelResultsMenu model={model} projectId={projectId} imageLayerId={imageLayerId}
        workflow="inference" validationLabelCount={validationLabelCount}
        buttonId={"singleModelResults" + index}
        className="dashboard-button dashboard-button-light" artifactItems={artifactItems} />
      {model.artifacts?.zipStatusMessage && (
        <ModelResultsStatusIndicator
          statusMessage={model.artifacts.zipStatusMessage}
          contextLabel={`Model: ${model.name} \u00b7 Results`}
        />
      )}
    </div>
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
