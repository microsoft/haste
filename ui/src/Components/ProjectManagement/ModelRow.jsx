// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { IconButton, Text, TooltipHost } from "@fluentui/react";
import { useContext } from "react";
import PropTypes from "prop-types";
import { apiDelete, apiPut } from "../../util/api";
import { AppContext } from "../../AppContext";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import ModelResultsButton from "./ModelResultsButton";
import ModelCancelButton from "../OtherComponents/ModelCancelButton";
import { limitTextLength } from "../../util/conversion";
import { fileDownload } from "../../util/file";
import CreateEditModelCheckpoint from "../CreateEditModelCheckpoint";

const ModelRow = ({ models, projectId, imageLayerId, imagerySource, eventTypes, fetchProjectDetails, setModalComponent, validationLabelCount }) => {
  ModelRow.propTypes = {
    projectId: PropTypes.string.isRequired,
    imageLayerId: PropTypes.string.isRequired,
    imagerySource: PropTypes.string.isRequired,
    models: PropTypes.array.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    setModalComponent: PropTypes.func.isRequired,
    validationLabelCount: PropTypes.number,
  };
  
  const { setDialog, setIsLoading } = useContext(AppContext);

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }


  async function handleDeletion(modelId) {
    setDialog();
    setIsLoading(true, "Removing Model...");

    try {
      await apiDelete(`DeleteModel?projectId=${projectId}&modelId=${modelId}`);
      await sleep(2000);
      setDialog("Success", "Model removed successfully.");
      fetchProjectDetails();
    } catch (error) {
      console.error("Error removing the model:", error);
      setDialog("Error", "There was an error removing the model. Please try again.");
    }

    setIsLoading(false);
  }

  const moreMenuOptions = (modelId) => {
    const model = models.find((m) => m.modelId === modelId);
    return {
      items: [
        {
          disabled: model.inferenceStatus !== "Processed",
          key: "AddModelTrainingToCatalog",
          text: "Add Model to Catalog",
          iconProps: { iconName: "ProductCatalog" },
          onClick: () => {
            setModalComponent(
              <CreateEditModelCheckpoint
                onClose={() => setModalComponent(null)}
                projectId={projectId}
                imageLayerId={imageLayerId}
                imagerySource={imagerySource}
                eventTypes={eventTypes}
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
    <>
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
          <tr key={index}>
            <td className="pe-3 custom-text-no-wrap">
              <TooltipHost
                content={model.name}
                delay={2}
                id={`modelNameTooltip${index}`}
              >
                <Text variant="small">
                  <span>{limitTextLength(model.name, false, 59)}</span>
                </Text>
              </TooltipHost>
            </td>
            <td className="pe-3 custom-text-no-wrap d-none d-xxl-table-cell">
              <Text variant="small">
                <span className="fw-semibold">Trained:</span> {trainDate}
              </Text>
            </td>
            <td className="pe-3 custom-text-no-wrap d-none d-xxl-table-cell">
              <TooltipHost
                content={model.userId}
                delay={2}
                id={`modelUserIdTooltip${index}`}
              >
                <Text variant="small">
                  <span className="fw-semibold">User: </span>
                  {userId}
                </Text>
              </TooltipHost>
            </td>
            <td className="pe-3 custom-text-no-wrap">
              <Text variant="medium">{labelsText}</Text>
            </td>
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
            <td className="pe-3 custom-text-no-wrap">
              <ModelResultsButton
                model={model}
                projectId={projectId}
                imageLayerId={imageLayerId}
                index={index}
                validationLabelCount={validationLabelCount}
              />
            </td>
            <td>
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
        );
      })}
    </>
  );
};

export default ModelRow;
