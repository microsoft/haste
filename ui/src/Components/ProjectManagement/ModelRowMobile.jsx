// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text, IconButton } from "@fluentui/react";
import React from "react";
import { useContext } from "react";
import { AppContext } from "../../AppContext";
import PropTypes from "prop-types";
import ModelResultsButton from "./ModelResultsButton";
import { limitTextLength } from "../../util/conversion";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import ModelCancelButton from "../OtherComponents/ModelCancelButton";
import CreateEditModelCheckpoint from "../CreateEditModelCheckpoint";
import { apiDelete } from "../../util/api";
import { fileDownload } from "../../util/file";

const ModelRowMobile = ({ models, projectId, imageLayerId, fetchProjectDetails, setModalComponent  }) => {
  ModelRowMobile.propTypes = {
    projectId: PropTypes.string.isRequired,
    imageLayerId: PropTypes.string.isRequired,
    models: PropTypes.array.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    setModalComponent: PropTypes.func.isRequired,
  };

  const { setDialog, setIsLoading } = useContext(AppContext);

  async function handleDeletion(modelId) {
    setDialog();
    setIsLoading(true, "Removing Model...");

    try {
      await apiDelete(`DeleteModel?projectId=${projectId}&modelId=${modelId}`);
      await sleep(2000);
      fetchProjectDetails();
    } catch (error) {
      console.error("Error removing the model:", error);
    }

    setIsLoading(false);
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  const moreMenuOptions = (modelId) => {
    const model = models.find((m) => m.modelId === modelId);
    return {
      items: [
        {
          className: 'd-none',
          disabled: model.inferenceStatus !== "Processed",
          key: "AddModelTrainingToCatalog",
          text: "Add Model to Catalog",
          iconProps: { iconName: "ProductCatalog" },
          onClick: () => {
            setModalComponent(
              <CreateEditModelCheckpoint
                onClose={() => setModalComponent(null)}
                projectId={projectId}
                imageLayer={imageLayerId}
                modelId={modelId}
                fetchProjectDetails={fetchProjectDetails}
                autoLaunchGuidedTour={true}
              />
            );
          },
        },
        {
          key: "ExportLabelsToGeoJson",
          text: "Export Labels to GeoJSON",
          iconProps: { iconName: "Download" },
          disabled: !model || model.labelsUrl === null,
          onClick: () => {
            if (model && model.labelsUrl) {
              if (import.meta.env.VITE_PROJECT_STORAGE_APIM_URL) {
                model.labelsUrl = model.labelsUrl.replace(
                  /^https?:\/\/[^/]+/,
                  import.meta.env.VITE_PROJECT_STORAGE_APIM_URL
                );
              }
              fileDownload(model.labelsUrl, setDialog);
            } else {
              setDialog("Error", "No labels available for export.");
            }
          },
        },
        {
          key: "remove",
          text: "Remove",
          iconProps: { iconName: "Delete" },
          onClick: () => {
            setDialog("Important", `Do you want to remove the model?`, [
              {
                type: "primary",
                key: "yes",
                text: "Yes",
                onClick: () => handleDeletion(modelId),
              },
              {
                type: "default",
                key: "no",
                text: "No",
                onClick: () => setDialog(),
              },
            ]);
          },
        },
      ],
    };
  };

  return (
    <React.Fragment key={"models_" + projectId + "_" + imageLayerId}>
      {models != null && models.length > 0 ? (
        <tr>
          <td>
            <Text
              variant="small"
              className="me-4 fw-semibold custom-text-color"
            >
              Models
            </Text>
          </td>
        </tr>
      ) : (
        <tr>
          <td>
            <Text variant="small">
              No model available for this layer
            </Text>
          </td>
        </tr>
      )}
      {models.map((model, index) => {
        const trainDate = model.trainDate
          ? `${model.trainDate.substring(0, 10)} ${model.trainDate.substring(11, 19)}`
          : "";
        const userId = limitTextLength(model.userId, false, 35);
        const labelsText = model.labelsCount !== undefined ? `${model.labelsCount} Labels` : "";
        const statusMessage =
          (model.statusMessage || "") + (model.inferenceStatusMessage || "");
        const isInference = !!model.inferenceStatus;

        return (
          <React.Fragment key={"model_" + projectId + "_" + imageLayerId + "_" + index}>
            <tr >
              <td className="custom-text-no-wrap pt-1">
                <Text variant="small">
                  <span className="fw-semibold ">Name:</span>{" "}<span>{model.name}</span>
                </Text>
              </td>
            </tr>
            <tr>
              <td>
                <Text variant="small">
                  <span className="fw-semibold ">Trained:</span>{" "}
                  {trainDate}
                </Text>
              </td>
            </tr>
            <tr>
              <td className="pe-3 custom-text-no-wrap">
                <Text variant="small">
                  <span className="fw-semibold">Using {labelsText}</span>
                </Text>
              </td>
            </tr>
            <tr>
              <td className="pe-3 custom-text-no-wrap">
                <Text variant="small">
                  <span className="fw-semibold">User:</span> {userId}
                </Text>
              </td>
            </tr>
            <tr>
              <td className="pe-3 custom-text-no-wrap d-flex align-items-center">

                <StatusIndicator
                  currentStep={isInference ? model.inferenceCurrentStep : model.currentStep}
                  totalSteps={isInference ? model.inferenceTotalSteps : model.totalSteps}
                  progressPct={isInference ? model.inferenceProgressPct : model.progressPct}
                  status={isInference ? model.inferenceStatus : model.status}
                  statusMessage={statusMessage}
                  id={isInference ? `singleModelInferenceStatus${index}` : `singleModelTrainStatus${index}`}
                  prefix={isInference ? "Inference" : "Training"}
                />

                <ModelCancelButton
                  model={model}
                  projectId={projectId}
                  imageLayerId={imageLayerId}
                  fetchProjectDetails={fetchProjectDetails}
                />
              </td>
            </tr>
            <tr className="">
              <td className="pe-3 custom-text-no-wrap pb-2">
                <ModelResultsButton
                  model={model}
                  projectId={projectId}
                  imageLayerId={imageLayerId}
                  index={index}
                />
              </td>
            </tr>
            <tr className="model-mobile-row">
              <td className="pe-3 custom-text-no-wrap pb-2">
                <IconButton
                  id={`singleModelMoreOptions${index}`}
                  className="no-dropdown-icon"
                  menuProps={moreMenuOptions(model.modelId)}
                  iconProps={{ iconName: "more" }}
                  title="Menu"
                  ariaLabel="Menu"
                />
              </td>
            </tr>
          </React.Fragment>
        );
      })}
    </React.Fragment >
  );
};

export default ModelRowMobile;
