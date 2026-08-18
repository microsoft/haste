// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import React, { useState, useContext, useEffect } from "react";
import { DatePicker } from "@fluentui/react-datepicker-compat";
import {
  Button,
  Combobox,
  Option,
  Field,
  Input,
  Textarea,
  Label,
  Link,
  Text,
  OverlayDrawer,
  DrawerHeader,
  DrawerHeaderTitle,
  DrawerBody,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import { useDrawerAnimation } from "../util/useDrawerAnimation";

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

  const { open, requestClose } = useDrawerAnimation(onClose);

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

    const eventTypesError = projectId === undefined
      ? validateEventTypes(eventTypes)
      : "";

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
    <OverlayDrawer
      open={open}
      position="end"
      size="medium"
      style={{ width: "560px" }}
      onOpenChange={(_, { open }) => {
        if (!open) requestClose();
      }}
    >
      <DrawerHeader className="pt-3">
        <DrawerHeaderTitle
          action={
            <Button
              appearance="subtle"
              icon={<FluentIcon name="Cancel" />}
              aria-label="Close panel"
              onClick={requestClose}
            />
          }
        >
          <span className="d-flex align-items-center">
            <FluentIcon
              name="FolderHorizontal"
              className="me-2 modal-icon"
            />
            {projectId ? "Edit Project" : "Start a Project"}
          </span>
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody>
        <div className="p-3" style={{ width: "100%" }}>
          <div className="row mb-2">
            <div className="col-12 p-0">
              <Field label="Name" required validationMessage={componentState.nameError}>
                <Input
                  id="createEditProjectName"
                  value={componentState.name}
                  onChange={(e, data) =>
                    onFormChange(
                      "name",
                      data.value,
                      setComponentState,
                      componentState
                    )
                  }
                  maxLength={250}
                />
              </Field>
            </div>
          </div>
          <div className="row mb-2">
            <div className="col-12 p-0">
              <Field
                label="Description"
                hint={
                  componentState.description.length + "/2000 " + "characters"
                }
              >
                <Textarea
                  id="createEditProjectDescription"
                  rows={5}
                  value={componentState.description}
                  onChange={(e, data) =>
                    onFormChange(
                      "description",
                      data.value,
                      setComponentState,
                      componentState
                    )
                  }
                  maxLength={2000}
                />
              </Field>
            </div>
          </div>

          <div className="row mb-1 mt-4">
            <div className="col-12 p-0">
              <Field label="Event Date" required>
                <DatePicker
                  id="createEditProjectEventDate"
                  placeholder="Select a date..."
                  aria-label="Select a date"
                  onSelectDate={(e) =>
                    onFormChange(
                      "eventDate",
                      e,
                      setComponentState,
                      componentState
                    )
                  }
                  value={
                    componentState.eventDate !== ""
                      ? new Date(componentState.eventDate)
                      : null
                  }
                  className="mb-3"
                />
              </Field>
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
                <Field
                  className="flex-grow-1"
                  validationMessage={componentState.affectedCountriesError}
                >
                  <Combobox
                    id="createEditProjectAffectedCountries"
                    aria-label="ExpandCountries"
                    placeholder="Select country"
                    freeform
                    autoComplete="on"
                    onOptionSelect={(e, data) => {
                      const option = componentState.countries.find(
                        (c) => c.key === data.optionValue
                      );
                      if (option) {
                        handleCountryAdditionOnSelect(option);
                      }
                    }}
                  >
                    {componentState.countries.map((option) => (
                      <Option key={option.key} value={option.key} text={option.text}>
                        {option.text}
                      </Option>
                    ))}
                  </Combobox>
                </Field>
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
                <Button
                  appearance="subtle"
                  aria-label="RemoveAffectedCountry"
                  icon={<FluentIcon name="Delete" />}
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
                <Field
                  className="flex-grow-1"
                  validationMessage={componentState.eventTypesError}
                >
                  <Combobox
                    id="createEditProjectEventTypes"
                    aria-label="ExpandEventTypes"
                    placeholder="Select event types"
                    freeform
                    autoComplete="on"
                    disabled={projectId !== undefined}
                    onOptionSelect={(e, data) => {
                      const option = componentState.eventTypeList.find(
                        (c) => c.key === data.optionValue
                      );
                      if (option) {
                        handleEventTypesAdditionOnSelect(option);
                      }
                    }}
                  >
                    {componentState.eventTypeList.map((option) => (
                      <Option key={option.key} value={option.key} text={option.text}>
                        {option.text}
                      </Option>
                    ))}
                  </Combobox>
                </Field>
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
                {projectId === undefined && (
                  <Button
                    appearance="subtle"
                    aria-label="RemoveEventType"
                    icon={<FluentIcon name="Delete" />}
                    onClick={() =>
                      removeEventType(
                        eventType,
                        setComponentState,
                        componentState,
                        setSelectedCountry
                      )
                    }
                  />
                )}
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

                <Text id="createEditProjectPrimaryClasses">
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
              <Button appearance="primary" className="me-2" onClick={validateBeforeSubmit} id="createEditProjectSubmit">
                Submit
              </Button>
              <Button onClick={requestClose}>Cancel</Button>
            </div>
          </div>
        </div>
      </DrawerBody>
    </OverlayDrawer>
  );
};

export default CreateEditProjectModal;
