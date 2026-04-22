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

const ImageLayerInfoMobile = ({ item, setModalComponent, fetchProjectDetails, setComponentState  }) => {
  ImageLayerInfoMobile.propTypes = {
    item: PropTypes.object.isRequired,
    setModalComponent: PropTypes.func.isRequired,
    fetchProjectDetails: PropTypes.func.isRequired,
    setComponentState: PropTypes.func.isRequired,
  };

  const navigate = useNavigate();
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

          <div style={{ borderBottom: "1px solid #ccc" }} className="pb-2 pt-2">
            <DefaultButton
              id={"singleProjectLabelingToolLaunch" + item.imageLayerId}
              className="dashboard-button"
              onClick={() =>
                navigate(`/labeling-tool/${item.projectId}/${item.imageLayerId}`)
              }
              disabled={item.status !== "Processed"}
            >
              Launch Labeling Tool
            </DefaultButton>{" "}
            <Text className="pe-4" variant="small">
              ({item.labelProjectCount})
            </Text>
          </div>

          <div style={{ borderBottom: "1px solid #ccc" }} className="pb-2 pt-2">
            <DefaultButton
              id={"singleProjectModelTraining" + item.imageLayerId}
              className="dashboard-button"
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
            </DefaultButton>{" "}
            <Text className="pe-4" variant="small">
              ({item.models && item.models.length > 0 ? item.models.length : 0})
            </Text>
          </div>
        </td>
      </tr>
    </React.Fragment >
  );
};

export default ImageLayerInfoMobile;
