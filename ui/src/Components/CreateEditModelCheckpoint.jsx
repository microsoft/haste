// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState, useContext, useEffect } from "react";
import { TextField, Link, Text } from "@fluentui/react";
import {
  DefaultButton,
  PrimaryButton,
} from "@fluentui/react/lib/Button";

import { apiPut } from "../util/api";
import { validateEmptyOrInvalid, validateRepeatedKeyInArray } from "../util/validation";
import { useNavigate } from "react-router-dom";
import UserMetadataCreator from "./UserMetadataCreator";
import ErrorMessage from "./OtherComponents/ErrorMessage";

import {
  createComponentDefaultState,
  onFormChange,
  addMetadata,
} from "./CreateEditModelCheckpointHelper";

import { AppContext } from "../AppContext";
import SectionModal from "./SectionModal";

import proptypes from "prop-types";

const CreateEditModelCheckpoint = ({
  onClose,
  projectId,
  imageLayerId,
  imagerySource,
  eventTypes,
  modelId,
}) => {
  CreateEditModelCheckpoint.propTypes = {
    onClose: proptypes.func.isRequired,
    projectId: proptypes.string.isRequired,
    imageLayerId: proptypes.string.isRequired,
    imagerySource: proptypes.string.isRequired,
    eventTypes: proptypes.array.isRequired,
    modelId: proptypes.string.isRequired,
  };

  const { setDialog, appParams, setIsLoading } =
    useContext(AppContext);
  const [componentState, setComponentState] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    async function initComponent() {
      setComponentState(
        await createComponentDefaultState(modelId, imageLayerId, imagerySource, eventTypes, projectId)
      );
    }

    initComponent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function validateBeforeSubmit() {
    const {
      baseModelName,
      userMetadata
    } = componentState;

    const baseModelNameError = validateEmptyOrInvalid(true, "Name", baseModelName);
    const userMetadataError = validateRepeatedKeyInArray(
      "Metadata",
      userMetadata
    );


    if (baseModelNameError || userMetadataError) {
      setComponentState({
        ...componentState,
        baseModelNameError: baseModelNameError,
        userMetadataError: userMetadataError,
      });
      return;
    }

    await save();
  }

  async function save() {
    setIsLoading(true, "Processing Model...");
    try {
      const modelToEdit = null; // Placeholder for future edit functionality
      if (modelToEdit) {
        await apiPut("PutModelCatalog/", componentState);
      } else {

        const additionalInfo = componentState.userMetadata.reduce((acc, item) => {
          acc[item.key] = item.value;
          return acc;
        }, {});


        const apiBody = {
          baseModelName: componentState.baseModelName,
          modelId: componentState.modelId,
          projectId: componentState.projectId,
          imageLayerId: componentState.imageLayerId,
          imagerySource: componentState.imagerySource,
          eventTypes: componentState.eventTypes,
          cataloguedByUser: appParams.userId,
          name: componentState.baseModelName,
          description: componentState.description,
          additionalInfo: additionalInfo,
          source: "haste"
        };



        const buttons = [
          {
            type: "primary",
            key: "close",
            text: "Close",
            onClick: () => {
              setDialog();
              navigate(`/project/${projectId}/${componentState.imageLayerId}`);
              navigate(0);
            },
          },
        ];
        const response = await apiPut("PutModelCatalog", apiBody);
        if (response === 409) {
          setDialog(
            "Error",
            "The model is already cataloged.",
            buttons);
        } else {
          setDialog("Success", "Model successfully cataloged", buttons);
        }
        onClose();
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

      title={"Add To Catalog"}
      body={
        <div className="modal-container p-1">
          <div className="row mb-2">
            <div className="col-12">
              <TextField
                id="createEditModelTrainingName"
                label="Name"
                maxLength={100}
                value={componentState.baseModelName}
                onChange={(e, newValue) =>
                  onFormChange(
                    newValue,
                    "baseModelName",
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.baseModelNameError}
              />
            </div>
          </div>

          <div className="row mb-2">
            <div className="col-12">
              <TextField
                id="createEditProjectDescription"
                multiline
                rows={5}
                label="Description"
                description={
                  componentState.description.length + "/2000 " + "characters"
                }
                value={componentState.description}
                onChange={(e, newValue) =>
                  onFormChange(
                    newValue,
                    "description",
                    setComponentState,
                    componentState
                  )
                }
                maxLength={2000}
              />
            </div>
          </div>

          <div className="row mt-4 mb-4">
            <div>
              <div className="col-12 d-flex flex-column box-highlight p-3 p-md-4 pb-2">
                <div className="col-12 pb-2">
                  <h6 className="m-0 pb-2">
                    Metadata
                  </h6>

                  <ErrorMessage errorMessage={componentState.userMetadataError} />

                  <div style={{ wordWrap: "break-word" }}>
                    Enables flexible tagging and categorization the model content. It supports dynamic metadata entries.
                  </div>
                </div>

                {componentState.userMetadata.map((metadata, index) => (
                  <UserMetadataCreator
                    key={"Metadata" + index}
                    metadata={metadata}
                    index={index}
                    setComponentState={setComponentState}
                    componentState={componentState}
                  />
                ))}

                <Link
                  id="createEditProjectAddPrimaryClass"
                  aria-label="AddPrimaryClass"
                  className="pb-2 mt-2"
                  onClick={() =>
                    addMetadata(setComponentState, componentState)
                  }
                >
                  Add Metadata

                </Link>
              </div>
            </div>
          </div>


          <div className="row mt-4
          ">
            <div className="col-12 d-flex justify-content-end">
              <PrimaryButton className="me-2" onClick={validateBeforeSubmit} id="createEditModelTrainingSubmit">
                Submit
              </PrimaryButton>
              <DefaultButton onClick={onClose}>Cancel</DefaultButton>
            </div>
          </div>
        </div>
      }
      onClose={onClose}
      icon="ProductCatalog"
    />
  );
};

export default CreateEditModelCheckpoint;
