// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { IconButton } from "@fluentui/react";
import React, { useContext } from "react";
import PropTypes from "prop-types";
import "../../assets/css/progress-bar.css";
import { apiPut } from "../../util/api";
import { AppContext } from "../../AppContext";

const ModelCancelButton = ({ model, projectId, imageLayerId, fetchProjectDetails }) => {
  ModelCancelButton.propTypes = {
    model: PropTypes.object.isRequired,
    projectId: PropTypes.string.isRequired,
    imageLayerId: PropTypes.string.isRequired,
  };

  const cancelLabel = (model.status === "Queued" || model.status === "InProgress") ? "Cancel Training" : "Cancel Inference";

  const { setDialog, setIsLoading } = useContext(AppContext);

  const handleCancel = async () => {
    setIsLoading(true, "Cancelling Job...");
    try {
      const apiBody = {
        modelId: model.modelId,
        projectId: projectId,
      };

      await apiPut("PutCancelModelQueueMessage/", apiBody);
      await fetchProjectDetails();
      setIsLoading(false);
    } catch (error) {
      setDialog("Error", error.message, []);
      setIsLoading(false);
    }
  };

  return (
    <React.Fragment>
      {model.status == "InProgress" || model.status == "Queued" || model.inferenceStatus == "InProgress" || model.inferenceStatus == "Queued" ? (
        <IconButton className="cancel-model-process-button" iconProps={{ iconName: "cancel" }} title={cancelLabel} onClick={handleCancel} />
      ) : null}
    </React.Fragment>
  );
};

export default ModelCancelButton;
