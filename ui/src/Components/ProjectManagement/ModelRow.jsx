// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import {
  Tooltip,
  Button,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { useContext } from "react";
import PropTypes from "prop-types";
import { apiDelete, apiPut } from "../../util/api";
import { AppContext } from "../../AppContext";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import ModelResultsButton from "./ModelResultsButton";
import EmbeddingModelRow from "./EmbeddingModelRow";
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
          icon: <FluentIcon name="ProductCatalog" />,
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
          icon: <FluentIcon name="Download" />,
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
          icon: <FluentIcon name="Delete" />,
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
        if (model.modelType === "embedding") {
          return (
            <EmbeddingModelRow
              key={model.modelId || index}
              model={model}
              projectId={projectId}
              imageLayerId={imageLayerId}
              index={index}
              fetchProjectDetails={fetchProjectDetails}
              validationLabelCount={validationLabelCount}
            />
          );
        }
        const trainDate = model.trainDate
          ? `${model.trainDate.substring(0, 10)} ${model.trainDate.substring(11, 19)}`
          : "";
        const userId = limitTextLength(model.userId, false, 35);
        const labelsText = model.labelsCount !== undefined ? `${model.labelsCount} Labels` : "";
        const statusMessage =
          (model.statusMessage || "") + (model.inferenceStatusMessage || "");
        const isInference = !!model.inferenceStatus;

        return (
          <div className="lmodel" key={model.modelId || index}>
            <div className="lmodel-info">
              <div className="lmodel-name-row">
                <Tooltip content={model.name} relationship="label">
                  <span className="lmodel-name" id={`modelNameTooltip${index}`}>
                    {limitTextLength(model.name, false, 59)}
                  </span>
                </Tooltip>
                {labelsText && (
                  <span className="lmodel-chip">{labelsText}</span>
                )}
              </div>
              <div className="lmodel-meta">
                {trainDate && (
                  <span>
                    <b>Trained:</b> {trainDate}
                  </span>
                )}
                {trainDate && model.userId && (
                  <span className="lmodel-meta-sep">&middot;</span>
                )}
                {model.userId && (
                  <Tooltip content={model.userId} relationship="label">
                    <span id={`modelUserIdTooltip${index}`}>
                      <b>User:</b> {userId}
                    </span>
                  </Tooltip>
                )}
              </div>
            </div>
            <div className="lmodel-status">
              <StatusIndicator
                currentStep={isInference ? model.inferenceCurrentStep : model.currentStep}
                totalSteps={isInference ? model.inferenceTotalSteps : model.totalSteps}
                progressPct={isInference ? model.inferenceProgressPct : model.progressPct}
                status={isInference ? model.inferenceStatus : model.status}
                statusMessage={statusMessage}
                id={isInference ? `singleModelInferenceStatus${index}` : `singleModelTrainStatus${index}`}
                prefix={isInference ? "Inference" : "Training"}
                contextLabel={`Model: ${model.name} \u00b7 ${isInference ? "Inference" : "Training"}`}
              />
              <ModelCancelButton
                model={model}
                projectId={projectId}
                imageLayerId={imageLayerId}
                fetchProjectDetails={fetchProjectDetails}
              />
            </div>
            <div className="lmodel-actions">
              <ModelResultsButton
                model={model}
                projectId={projectId}
                imageLayerId={imageLayerId}
                index={index}
                validationLabelCount={validationLabelCount}
              />
              <Menu positioning="below-end">
                <MenuTrigger disableButtonEnhancement>
                  <Button
                    id={`singleModelMoreOptions${index}`}
                    appearance="subtle"
                    className="no-dropdown-icon"
                    icon={<FluentIcon name="More" />}
                    title="Menu"
                    aria-label="Menu"
                  />
                </MenuTrigger>
                <MenuPopover>
                  <MenuList>
                    {moreMenuOptions(model.modelId).items.map((mi) => (
                      <MenuItem
                        key={mi.key}
                        className={mi.className}
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
            </div>
          </div>
        );
      })}
    </>
  );
};

export default ModelRow;
