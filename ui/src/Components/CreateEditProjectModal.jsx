// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useState, useContext, useEffect } from "react";
import {
  TextField,
  DefaultButton,
  PrimaryButton,
  ComboBox,
  IconButton,
  Label,
  Link,
  DatePicker,
  Text,
} from "@fluentui/react";

import {
  createComponentDefaultState,
  addPrimaryClass,
  addAffectedCountry,
  removeAffectedCountry,
  addEventType,
  removeEventType,
  onFormChange,
} from "./CreateEditProjectModalHelper";

import PrimaryClassCreator from "./PrimaryClassCreator";
import { apiPut } from "../util/api";
import SectionModal from "./SectionModal";
import ErrorMessage from "./OtherComponents/ErrorMessage";
import proptypes from "prop-types";
import {
  validateEmptyOrInvalid,
  validateEmpty,
  validateAtLeastSomeNumber,
  validatePrimaryClasses,
  validateEventTypes
} from "../util/validation";
import { AppContext } from "../AppContext";
import { useNavigate } from "react-router-dom";

const CreateEditProjectModal = ({ onClose, projectId }) => {
  CreateEditProjectModal.propTypes = {
    onClose: proptypes.func.isRequired,
    projectId: proptypes.string,
  };

  const [componentState, setComponentState] = useState(null);
  const [selectedCountry, setSelectedCountry] = useState(null);
  const [selectedEventType, setSelectedEventType] = useState(null);
  const { setDialog, appParams, setIsLoading } = useContext(AppContext);
  const navigate = useNavigate();

  useEffect(() => {
    async function initComponent() {
      setIsLoading(true);
      setComponentState(await createComponentDefaultState(projectId));
      setIsLoading(false);
    }

    initComponent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function validateBeforeSubmit() {
    const { name, eventTypes, eventDate, affectedCountries, primaryClasses } = componentState;
    const nameError = validateEmptyOrInvalid(true, "Name", name);
    const eventDateError = validateEmpty("Event Date", eventDate);
    const affectedCountriesError = validateAtLeastSomeNumber(
      "Affected Countries",
      affectedCountries,
      1
    );

    const primaryClassesError = validatePrimaryClasses(
      primaryClasses
    );

    // Only validate event types if creating a new project. Old projects may not have any.
    var eventTypesError = "";
    validateEventTypes(
      eventTypes
    );

    if (nameError || eventTypesError || eventDateError || affectedCountriesError || primaryClassesError) {
      setComponentState({
        ...componentState,
        nameError: nameError,
        eventTypesError: eventTypesError,
        eventDateError: eventDateError,
        affectedCountriesError: affectedCountriesError,
        primaryClassesError: primaryClassesError,
      });
      return;
    }

    await save();
  }

  function handleCountryAddition() {
    if (selectedCountry) {
      addAffectedCountry(setComponentState, componentState, selectedCountry);
      setSelectedCountry(null);
    }
  }

  function handleCountryAdditionOnSelect(option) {
    if (option) {
      addAffectedCountry(setComponentState, componentState, option);
      setSelectedCountry(null);
    }
  }

  function handleEventTypesAddition() {
    if (selectedEventType) {
      addEventType(setComponentState, componentState, selectedEventType);
      setSelectedEventType(null);
    }
  }

  function handleEventTypesAdditionOnSelect(option) {
    if (option) {
      addEventType(setComponentState, componentState, option);
      setSelectedEventType(null);
    }
  }

  async function save() {
    var tempProjectId = "";
    const buttons = [
      {
        type: "primary",
        key: "continue",
        text: "Continue",
        onClick: () => {
          setDialog("", "", []);
          navigate("/project/" + tempProjectId);
          navigate(0);
        },
      },
    ];

    setIsLoading(true, "Processing project...");

    try {
      if (projectId !== undefined) {
        const response = await apiPut("PutProject", componentState);
        tempProjectId = response.projectId;
        onClose();
        setIsLoading(false);
        setDialog(
          "Success",
          "Project successfully updated. Click 'Continue' to open it.",
          buttons
        );
      } else {
        const apiBody = {
          name: componentState.name,
          description: componentState.description,
          eventDate: componentState.eventDate,
          userId: appParams.userId,
          affectedCountries: componentState.affectedCountries,
          eventTypes: componentState.eventTypes,
          primaryClasses: componentState.primaryClasses,
        };

        const response = await apiPut("PutProject", apiBody);
        tempProjectId = response.projectId;
        onClose();
        setIsLoading(false);
        setDialog(
          "Success",
          "Project successfully created. Click 'Continue' to open it.",
          buttons
        );
      }
    } catch (error) {
      setIsLoading(false);
      setDialog(
        "Error",
        "There was an error while handling data, please try again later.",
        []
      );
    }
  }

  /* RENDER */
  if (!componentState) {
    return null;
  }

  return (
    <SectionModal
      title={projectId ? "Edit Project" : "Start a Project"}
      body={
        <div className="modal-container p-3">
          <div className="row mb-2">
            <div className="col-12 p-0">
              <TextField
                id="createEditProjectName"
                required
                label="Name"
                value={componentState.name}
                onChange={(e, newValue) =>
                  onFormChange(
                    "name",
                    newValue,
                    setComponentState,
                    componentState
                  )
                }
                errorMessage={componentState.nameError}
                maxLength={250}
              />
            </div>
          </div>
          <div className="row mb-2">
            <div className="col-12 p-0">
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
                    "description",
                    newValue,
                    setComponentState,
                    componentState
                  )
                }
                maxLength={2000}
              />
            </div>
          </div>

          <div className="row mb-1 mt-4">
            <div className="col-12 p-0">
              <Label className="me-2" required>
                Event Date
              </Label>
              <DatePicker
                id="createEditProjectEventDate"
                placeholder="Select a date..."
                ariaLabel="Select a date"
                onSelectDate={(e) =>
                  onFormChange(
                    "eventDate",
                    e,
                    setComponentState,
                    componentState
                  )
                }
                isRequired={componentState.eventDateError}
                value={
                  componentState.eventDate !== ""
                    ? new Date(componentState.eventDate)
                    : ""
                }
                className="mb-3"
              />
            </div>
          </div>

          <div className="row mb-1">
            <div className="col-12 d-flex flex-column p-0">
              <div className="col-12">
                <Label className="me-2" required>
                  Affected Countries
                </Label>
              </div>
              <div className="col-12 d-flex">
                <ComboBox
                  id="createEditProjectAffectedCountries"
                  ariaLabel="ExpandCountries"
                  options={componentState.countries}
                  placeholder="Select country"
                  allowFreeInput
                  onKeyUp={(e) => {
                    if (e.key === "Enter") {
                      handleCountryAddition();
                    }
                  }}
                  onItemClick={(e, option) => {
                    if (option) {
                      handleCountryAdditionOnSelect(option);
                    }
                  }}
                  autoComplete="on"
                  className="flex-grow-1"
                  onChange={(_, option) => setSelectedCountry(option)}
                  selectedKey={selectedCountry ? selectedCountry.key : null}
                  text=""
                  errorMessage={componentState.affectedCountriesError}
                />
              </div>

            </div>
          </div>

          {componentState.affectedCountries.map((affectedCountry, index) => (
            <div className="row ps-3 pe-3" key={"affectedCountry" + index}>
              <div
                className="col d-flex flex-grow-1 align-items-center mb-1 pb-1 pt-1 ps-0 pe-0"
                style={{ borderBottom: "1px solid #eaeaea" }}
              >
                {
                  componentState.countries.find(
                    (c) => c.key === affectedCountry
                  ).text
                }
              </div>
              <div
                className="col-auto d-flex align-items-center mb-1 pb-1 pt-1 ps-0 pe-0"
                style={{ borderBottom: "1px solid #eaeaea" }}
              >
                <IconButton
                  ariaLabel="RemoveAffectedCountry"
                  iconProps={{ iconName: "Delete" }}
                  onClick={() =>
                    removeAffectedCountry(
                      affectedCountry,
                      setComponentState,
                      componentState,
                      setSelectedCountry
                    )
                  }
                />
              </div>
            </div>
          ))}


          <div className="row mt-4">
            <div className="col-12 d-flex flex-column p-0">
              <div className="col-12">
                <Label className="me-2" required>
                  Event Types
                </Label>
              </div>
              <div className="col-12 d-flex">
                <ComboBox
                  id="createEditProjectEventTypes"
                  ariaLabel="ExpandEventTypes"
                  options={componentState.eventTypeList}
                  placeholder="Select event types"
                  allowFreeInput
                  disabled={projectId !== undefined}
                  onKeyUp={(e) => {
                    if (e.key === "Enter") {
                      handleEventTypesAddition();
                    }
                  }}
                  onItemClick={(e, option) => {
                    if (option) {
                      handleEventTypesAdditionOnSelect(option);
                    }
                  }}
                  autoComplete="on"
                  className="flex-grow-1"
                  onChange={(_, option) => setSelectedEventType(option)}
                  selectedKey={selectedEventType ? selectedEventType.key : null}
                  text=""
                  errorMessage={componentState.eventTypesError}
                />
              </div>

            </div>
          </div>

          {componentState.eventTypes.map((eventType, index) => (
            <div className="row ps-3 pe-3" key={"eventType" + index}>
              <div
                className="col d-flex flex-grow-1 align-items-center mb-1 pb-1 pt-1 ps-0 pe-0"
                style={{ borderBottom: "1px solid #eaeaea" }}
              >
                {
                  componentState.eventTypeList.find(
                    (c) => c.key === eventType
                  ).text
                }
              </div>
              <div
                className="col-auto d-flex align-items-center mb-1 pb-1 pt-1 ps-0 pe-0"
                style={{ borderBottom: "1px solid #eaeaea" }}
              >
                <IconButton
                  ariaLabel="RemoveEventType"
                  iconProps={{ iconName: "Delete" }}
                  onClick={() =>
                    removeEventType(
                      eventType,
                      setComponentState,
                      componentState,
                      setSelectedCountry
                    )
                  }
                />
              </div>
            </div>
          ))}

          <div className="row mt-4 mb-4">
            <div className="col-12 d-flex flex-column box-highlight p-4 pb-2">
              <div className="col-12 pb-2">
                <h6 className="m-0 pb-2">
                  Primary Classes
                  <span className="required-form-element"> *</span>
                </h6>

                <ErrorMessage errorMessage={componentState.primaryClassesError} />

                <Text variant="medium" id="createEditProjectPrimaryClasses">
                  These categories will be used to train the damage assessment model. Use the defaults here or edit them to define your own.
                </Text>
              </div>
              {componentState.primaryClasses.map((primaryClass, index) => (
                <PrimaryClassCreator
                  key={"primaryClass" + index}
                  primaryClass={primaryClass}
                  index={index}
                  setComponentState={setComponentState}
                  componentState={componentState}
                  projectId={projectId}
                  setDialog={setDialog}
                />
              ))}

              <Link
                id="createEditProjectAddPrimaryClass"
                aria-label="AddPrimaryClass"
                className="pb-2 mt-3"
                disabled={projectId !== undefined}
                onClick={() =>
                  addPrimaryClass(setComponentState, componentState)
                }
              >
                Add Class
              </Link>
            </div>
          </div>

          <div className="row">
            <div className="col-12 d-flex justify-content-end">
              <PrimaryButton className="me-2" onClick={validateBeforeSubmit} id="createEditProjectSubmit">
                Submit
              </PrimaryButton>
              <DefaultButton onClick={onClose}>Cancel</DefaultButton>
            </div>
          </div>
        </div>
      }
      onClose={onClose}
      icon="OpenFolderHorizontal"
    />
  );
};

export default CreateEditProjectModal;
