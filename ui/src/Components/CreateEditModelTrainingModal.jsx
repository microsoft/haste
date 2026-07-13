// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState, useContext, useEffect } from "react";
import { TextField, Dropdown } from "@fluentui/react";
import {
  DefaultButton,
  ActionButton,
  PrimaryButton,
  IconButton,
} from "@fluentui/react/lib/Button";

import { apiPut } from "../util/api";
import { validateEmptyOrInvalid, validateInt, validateFloat } from "../util/validation";
import { useNavigate } from "react-router-dom";
import { initGuidedTourState } from "./GuidedTourHelper";
import BaseModelDropdown from "./BaseModelDropdown";

import {
  createComponentDefaultState,
  onFormChange,
} from "./CreateEditModelTrainingHelper";

import { AppContext } from "../AppContext";
import SectionModal from "./SectionModal";

import proptypes from "prop-types";

const CreateEditModelTrainingModal = ({
  onClose,
  projectId,
  imageLayer,
  modelToEdit,
  guidedTour,
  autoLaunchGuidedTour,
  eventTypes,
}) => {
  CreateEditModelTrainingModal.propTypes = {
    onClose: proptypes.func.isRequired,
    projectId: proptypes.string.isRequired,
    imageLayer: proptypes.object.isRequired,
    modelToEdit: proptypes.object,
    guidedTour: proptypes.string.isRequired,
    autoLaunchGuidedTour: proptypes.bool.isRequired,
    eventTypes: proptypes.array.isRequired,
  };
  
  const { setDialog, appParams, setIsLoading, initCurrentTour } =
    useContext(AppContext);
  const [componentState, setComponentState] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    async function initComponent() {
      setComponentState(
        await createComponentDefaultState(modelToEdit, imageLayer, projectId, eventTypes)
      );

      if (autoLaunchGuidedTour) {
        initCurrentTour(guidedTour);
      } else {
        initGuidedTourState(guidedTour, appParams.guidedTourProperties);
      }
    }

    initComponent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function validateBeforeSubmit() {
    const {
      name,
      learningRate,
      batchSize,
      maxEpochs,
    } = componentState;

    const nameError = validateEmptyOrInvalid(true, "Name", name);
    const learningRateError = validateFloat("Learning Rate", learningRate);
    const batchSizeError = validateInt("Batch Size", batchSize);
    const maxEpochsError = validateInt("Max Epochs", maxEpochs);

    if (nameError || learningRateError || batchSizeError || maxEpochsError) {
      setComponentState({
        ...componentState,
        nameError: nameError,
        learningRateError: learningRateError,
        batchSizeError: batchSizeError,
        maxEpochsError: maxEpochsError,
        viewParams:
          learningRateError !== "" ||
          batchSizeError !== "" ||
          maxEpochsError !== "",
      });
      return;
    }

    await save();
  }

  async function save() {
    setIsLoading(true, "Processing Model...");
    try {
      if (modelToEdit) {
        await apiPut("PutRunModelQueueMessage/", componentState);
      } else {
        const apiBody = {
          projectId: componentState.projectId,
          imageLayerId: componentState.imageLayerId,
          name: componentState.name,
          initialWeightsUrl: componentState.initialWeightsUrl,
          learningRate: componentState.learningRate,
          batchSize: componentState.batchSize,
          maxEpochs: componentState.maxEpochs,
          userId: appParams.userId,
        };
        const buttons = [
          {
            type: "primary",
            key: "close",
            text: "Close",
            onClick: () => {
              setDialog();
              navigate(`/project/${projectId}/${imageLayer.imageLayerId}`);
              navigate(0);
            },
          },
        ];
        await apiPut("PutRunModelQueueMessage", apiBody);
        onClose();
        setDialog("Success", "Model successfully created", buttons);
      }
    } catch (error) {
      setDialog(
        "Error",
        "There was an error while training the Model. Please try again later.",
        []
      );
    }
    setIsLoading(false);
  }

  if (!componentState) {
    return null;
  }

  return (
    <SectionModal
      modalCurrentTour={guidedTour}
      title={modelToEdit ? "Edit Model" : "New Model"}
      body={
        <>
          <div className="row mb-2">
            <div className="col-12">
              <TextField
                id="createEditModelTrainingName"
                label="Name"
                value={componentState.name}
                onChange={(e, newValue) =>
                  onFormChange(
                    newValue,
                    "name",
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.nameError}
              />
            </div>
          </div>
          <div className="row mb-2">
            <div className="col-12">

              <BaseModelDropdown
                componentState={componentState}
                setComponentState={setComponentState}
                onFormChange={onFormChange}
              />
            </div>
          </div>
          <div className="row mb-4">
            <div className="col-12 d-flex align-items-center">
              <ActionButton
                id="createEditModelTrainingParams"
                iconProps={{
                  iconName: componentState.viewParams
                    ? "ChevronDown"
                    : "ChevronRight",
                }}
                styles={{ root: { padding: 0, border: "none" } }}
                onClick={() =>
                  onFormChange(
                    !componentState.viewParams,
                    "viewParams",
                    setComponentState,
                    componentState
                  )
                }
              >
                Params
              </ActionButton>
            </div>

            {componentState.viewParams && (
              <div className="col-12 flex-column flex-md-row d-flex">
                <TextField
                  id="createEditModelTrainingLearningRate"
                  label="Learning Rate"
                  className="me-0 me-md-4 mb-2"
                  value={componentState.learningRate}
                  onChange={(e, newValue) =>
                    onFormChange(
                      newValue,
                      "learningRate",
                      setComponentState,
                      componentState
                    )
                  }
                  errorMessage={componentState.learningRateError}
                  required
                />
                <TextField
                  id="createEditModelTrainingBatchSize"
                  label="Batch Size"
                  className="me-0 me-md-4 mb-2"
                  value={componentState.batchSize}
                  onChange={(e, newValue) =>
                    onFormChange(
                      newValue,
                      "batchSize",
                      setComponentState,
                      componentState
                    )
                  }
                  errorMessage={componentState.batchSizeError}
                  required
                />
                <TextField
                  id="createEditModelTrainingMaxEpochs"
                  label="Max Epochs"
                  value={componentState.maxEpochs}
                  onChange={(e, newValue) =>
                    onFormChange(
                      newValue,
                      "maxEpochs",
                      setComponentState,
                      componentState
                    )
                  }
                  errorMessage={componentState.maxEpochsError}
                  className="mb-2"
                  required
                />
              </div>
            )}
          </div>
          <div className="row">
            <div className="col-12 d-flex justify-content-end">
              <PrimaryButton className="me-2" onClick={validateBeforeSubmit} id="createEditModelTrainingSubmit">
                Submit
              </PrimaryButton>
              <DefaultButton onClick={onClose}>Cancel</DefaultButton>
            </div>
          </div>
        </>
      }
      onClose={onClose}
      icon="OpenFolderHorizontal"
    />
  );
};

export default CreateEditModelTrainingModal;
