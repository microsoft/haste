// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Components
import { Button } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import React, { useContext, useRef, useState } from "react";
import PropTypes from "prop-types";
import "../../assets/css/progress-bar.css";
import { apiPut } from "../../util/api";
import { AppContext } from "../../AppContext";
import { getModelCancellationLabel } from "../CatalogInferenceHelper";

const ModelCancelButton = ({ model, projectId, fetchProjectDetails }) => {

  const cancelLabel = getModelCancellationLabel(model);
  const [cancelling, setCancelling] = useState(false);
  const cancellingRef = useRef(false);
  const { setDialog, setIsLoading } = useContext(AppContext);

  const handleCancel = async () => {
    if (cancellingRef.current || !cancelLabel) return;
    cancellingRef.current = true;
    setCancelling(true);
    setIsLoading(true, "Cancelling Job...");
    try {
      const apiBody = {
        modelId: model.modelId,
        projectId: projectId,
      };

      const response = await apiPut("PutCancelModelQueueMessage/", apiBody);
      if (response === 409) {
        throw new Error("Cancellation conflicts with the current model state. Refresh the model and try again.");
      }
      if (await fetchProjectDetails() === false) {
        throw new Error("Cancellation was requested, but model rows could not be refreshed. Check the model status before retrying.");
      }
    } catch (error) {
      console.error(error);
      setDialog("Error", error.message || "An error occurred while cancelling the model.", []);
    } finally {
      cancellingRef.current = false;
      setCancelling(false);
      setIsLoading(false);
    }
  };

  return (
    <React.Fragment>
      {cancelLabel ? (
        <Button appearance="subtle" className="cancel-model-process-button" icon={<FluentIcon name="cancel" />} title={cancelLabel} aria-label={cancelLabel} onClick={handleCancel} disabled={cancelling} />
      ) : null}
    </React.Fragment>
  );
};

ModelCancelButton.propTypes = {
  model: PropTypes.object.isRequired,
  projectId: PropTypes.string.isRequired,
  imageLayerId: PropTypes.string.isRequired,
  fetchProjectDetails: PropTypes.func.isRequired,
};

export default ModelCancelButton;
