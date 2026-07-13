// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Text } from "@fluentui/react";
import PropTypes from "prop-types";
import { DefaultButton } from "@fluentui/react";
import React from "react";
import StatusIndicator from "../OtherComponents/StatusIndicator";
import { useNavigate } from "react-router-dom";
import CreateEditModelTrainingModal from "../CreateEditModelTrainingModal";
import CreateEditEmbeddingModal from "../CreateEditEmbeddingModal";

const ImageLayerInfoMobile = ({ item, setModalComponent, fetchProjectDetails, setComponentState, eventTypes  }) => {
  ImageLayerInfoMobile.propTypes = {
    item: PropTypes.object.isRequired,
    setModalComponent: PropTypes.func.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    setComponentState: PropTypes.func.isRequired,
    eventTypes: PropTypes.array.isRequired,
  };

  const navigate = useNavigate();

  // Mirror LayerRow's desktop logic: layers created with the "building"
  // embedding workflow expose an Embed action (kicks off an embedding job)
  // instead of the Launch Labeling Tool / Train Model actions.
  const isBuildingWorkflow = item.workflowType === "building";
  const embeddingModels =
    (item.models || []).filter((m) => m.modelType === "embedding") || [];

  function handleEmbed() {
    setModalComponent(
      <CreateEditEmbeddingModal
        onClose={() => setModalComponent(null)}
        projectId={item.projectId}
        imageLayer={item}
        fetchProjectDetails={fetchProjectDetails}
      />
    );
  }

  return (
    <React.Fragment key={"imageLayerInfoMobile_" + item.projectId + "_" + item.imageLayerId}>
      <tr>
        <td
          className="dashboard-table-for-inner-table-td custom-text-no-wrap"
        >
          <div className="pb-2">
            <Text
              variant="small"
              className="me-4 fw-semibold custom-text-color"
            >
              Layer Tools
            </Text>
          </div>

          <div style={{ borderBottom: "1px solid #ccc" }} className="pb-2">
            <StatusIndicator
              id={"singleProjectImageLayerStatus" + item.imageLayerId}
              currentStep={item.currentStep}
              totalSteps={item.totalSteps}
              progressPct={item.progressPct}
              status={item.status}
              statusMessage={item.statusMessage}
              prefix="Imagery"
            />
          </div>

          {isBuildingWorkflow ? (
            <div style={{ borderBottom: "1px solid #ccc" }} className="pb-2 pt-2">
              <DefaultButton
                id={"singleProjectEmbed" + item.imageLayerId}
                className="dashboard-button"
                styles={{ root: { width: "100%" } }}
                onClick={handleEmbed}
                disabled={
                  item.status !== "Processed" || !item.buildingFootprintsUrl
                }
              >
                Embed
              </DefaultButton>
              <Text className="d-block pt-1" variant="small">
                Embeddings: {embeddingModels.length}
              </Text>
            </div>
          ) : (
            <>
              <div style={{ borderBottom: "1px solid #ccc" }} className="pb-2 pt-2">
                <DefaultButton
                  id={"singleProjectLabelingToolLaunch" + item.imageLayerId}
                  className="dashboard-button"
                  styles={{ root: { width: "100%" } }}
                  onClick={() =>
                    navigate(`/labeling-tool/${item.projectId}/${item.imageLayerId}`)
                  }
                  disabled={item.status !== "Processed"}
                >
                  Launch Labeling Tool
                </DefaultButton>
                <Text className="d-block pt-1" variant="small">
                  Label projects: {item.labelProjectCount}
                </Text>
              </div>

              <div style={{ borderBottom: "1px solid #ccc" }} className="pb-2 pt-2">
                <DefaultButton
                  id={"singleProjectModelTraining" + item.imageLayerId}
                  className="dashboard-button"
                  styles={{ root: { width: "100%" } }}
                  onClick={() =>
                    setModalComponent(
                      <CreateEditModelTrainingModal
                        onClose={() => setModalComponent(null)}
                        projectId={item.projectId}
                        imageLayer={item}
                        fetchProjectDetails={fetchProjectDetails}
                        setImageLayerComponentState={setComponentState}
                        guidedTour="createEditModelTrainingModalGuide"
                        autoLaunchGuidedTour={true}
                      />
                    )
                  }
                  disabled={item.status !== "Processed" || item.labelProjectCount < 1}
                >
                  Train Model
                </DefaultButton>
                <Text className="d-block pt-1" variant="small">
                  Models: {item.models && item.models.length > 0 ? item.models.length : 0}
                </Text>
              </div>
            </>
          )}

          <div style={{ borderBottom: "1px solid #ccc" }} className="pb-2 pt-2">
            <DefaultButton
              id={"singleProjectBuildingValidation" + item.imageLayerId}
              className="dashboard-button"
              styles={{ root: { width: "100%" } }}
              onClick={() =>
                navigate(`/validation/${item.projectId}/${item.imageLayerId}`)
              }
              disabled={!item.buildingFootprintsUrl}
            >
              Launch Validation Tool
            </DefaultButton>
            <Text className="d-block pt-1" variant="small">
              Validation labels: {item.validationLabelCount || 0}
            </Text>
          </div>
        </td>
      </tr>
    </React.Fragment >
  );
};

export default ImageLayerInfoMobile;
