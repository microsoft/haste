// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState, useContext, useEffect } from "react";
import {
  Button,
  Field,
  Input,
  OverlayDrawer,
  DrawerHeader,
  DrawerHeaderTitle,
  DrawerBody,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import { useDrawerAnimation } from "../util/useDrawerAnimation";

import { apiPut } from "../util/api";
import { validateEmptyOrInvalid, validateInt, validateFloat } from "../util/validation";
import { useNavigate } from "react-router-dom";
import { initGuidedTourState, setGuidedTourState } from "./GuidedTourHelper";
import BaseModelDropdown from "./BaseModelDropdown";

import {
  createComponentDefaultState,
  fetchModelCatalog,
  onFormChange,
} from "./CreateEditModelTrainingHelper";

import { AppContext } from "../AppContext";

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
  const { open, requestClose } = useDrawerAnimation(onClose);

  useEffect(() => {
    async function initComponent() {
      // Show the app loading overlay while the model catalog loads, then
      // reveal the panel (mirrors the create-project flow).
      setIsLoading(true, "Loading pre-trained models...");
      const baseState = createComponentDefaultState(
        modelToEdit,
        imageLayer,
        projectId
      );
      const cataloguedModels = await fetchModelCatalog(imageLayer, eventTypes);
      setComponentState({
        ...baseState,
        cataloguedModels,
        catalogLoading: false,
      });
      setIsLoading(false);

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
    <OverlayDrawer
      position="end"
      open={open}
      onOpenChange={(_, d) => {
        if (!d.open) requestClose();
      }}
      className="section-panel-drawer"
    >
      <DrawerHeader className="section-panel-header">
        <DrawerHeaderTitle
          action={
            <div className="d-flex">
              {guidedTour && (
                <Button
                  appearance="subtle"
                  icon={<FluentIcon name="Help" />}
                  aria-label="Help"
                  onClick={() =>
                    setGuidedTourState(
                      false,
                      initCurrentTour,
                      guidedTour,
                      appParams.guidedTourProperties
                    )
                  }
                />
              )}
              <Button
                appearance="subtle"
                icon={<FluentIcon name="Cancel" />}
                aria-label="Close"
                onClick={requestClose}
              />
            </div>
          }
        >
          <span className="section-panel-title">
            <FluentIcon name="ProductCatalog" className="modal-icon" />
            {modelToEdit ? "Edit Model" : "New Model"}
          </span>
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody>
        <div className="row mb-2">
          <div className="col-12">
            <Field label="Name" validationMessage={componentState.nameError}>
              <Input
                id="createEditModelTrainingName"
                value={componentState.name}
                onChange={(e, data) =>
                  onFormChange(
                    data.value,
                    "name",
                    setComponentState,
                    componentState
                  )
                }
              />
            </Field>
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
            <Button
              id="createEditModelTrainingParams"
              appearance="transparent"
              icon={
                <FluentIcon
                  name={
                    componentState.viewParams ? "ChevronDown" : "ChevronRight"
                  }
                />
              }
              style={{
                paddingLeft: 0,
                minWidth: 0,
                border: "none",
                fontWeight: 600,
                justifyContent: "flex-start",
              }}
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
            </Button>
          </div>

          {componentState.viewParams && (
            <div className="col-12 d-flex flex-column">
              <Field
                label="Learning Rate"
                className="mb-2"
                required
                validationMessage={componentState.learningRateError}
              >
                <Input
                  id="createEditModelTrainingLearningRate"
                  value={componentState.learningRate}
                  onChange={(e, data) =>
                    onFormChange(
                      data.value,
                      "learningRate",
                      setComponentState,
                      componentState
                    )
                  }
                />
              </Field>
              <Field
                label="Batch Size"
                className="mb-2"
                required
                validationMessage={componentState.batchSizeError}
              >
                <Input
                  id="createEditModelTrainingBatchSize"
                  value={componentState.batchSize}
                  onChange={(e, data) =>
                    onFormChange(
                      data.value,
                      "batchSize",
                      setComponentState,
                      componentState
                    )
                  }
                />
              </Field>
              <Field
                label="Max Epochs"
                className="mb-2"
                required
                validationMessage={componentState.maxEpochsError}
              >
                <Input
                  id="createEditModelTrainingMaxEpochs"
                  value={componentState.maxEpochs}
                  onChange={(e, data) =>
                    onFormChange(
                      data.value,
                      "maxEpochs",
                      setComponentState,
                      componentState
                    )
                  }
                />
              </Field>
            </div>
          )}
        </div>
        <div className="row">
          <div className="col-12 d-flex justify-content-end">
            <Button
              appearance="primary"
              className="me-2"
              onClick={validateBeforeSubmit}
              id="createEditModelTrainingSubmit"
            >
              Submit
            </Button>
            <Button onClick={requestClose}>Cancel</Button>
          </div>
        </div>
      </DrawerBody>
    </OverlayDrawer>
  );
};

export default CreateEditModelTrainingModal;
