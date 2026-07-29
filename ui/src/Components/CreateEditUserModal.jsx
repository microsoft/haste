// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { useEffect, useState, useContext } from "react";
import {
  Button,
  Field,
  Input,
  Dropdown,
  Option,
  OverlayDrawer,
  DrawerHeader,
  DrawerHeaderTitle,
  DrawerBody,
} from "@fluentui/react-components";
import { FluentIcon } from "../util/icons";
import { useDrawerAnimation } from "../util/useDrawerAnimation";


import { apiPut } from "../util/api";
import { useNavigate } from "react-router-dom";
import { AppContext } from "../AppContext";
import { createComponentDefaultState, onFormChange } from "./CreateEditUserModalHelper"
import { validateEmpty, validateEmail, validateAtLeastSomeNumber } from "../util/validation";
import proptypes from "prop-types";

const USER_ROLE_LABELS = {
  administrators: "Administrator",
  contributors: "Contributor",
};

const CreateEditUserModal = ({ onClose, userToEdit }) => {
  CreateEditUserModal.propTypes = {
    onClose: proptypes.func.isRequired,
    userToEdit: proptypes.object,
  };

  const { setDialog, setIsLoading, appParams } = useContext(AppContext);
  const navigate = useNavigate();
  const [componentState, setComponentState] = useState(null);
  const { open, requestClose } = useDrawerAnimation(onClose);

  useEffect(() => {
    async function initComponent() {
      setIsLoading(true);
      setComponentState(await createComponentDefaultState(userToEdit));
      setIsLoading(false);
    }

    initComponent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function validateBeforeSubmit() {
    const { name, email, userRoles } = componentState;
    const nameError = validateEmpty("Name", name);
    const emailError = validateEmail("User", email);
    const userRolesError = validateAtLeastSomeNumber("User roles", userRoles, 1);


    if (nameError || emailError || userRolesError) {
      setComponentState({
        ...componentState,
        nameError: nameError,
        emailError: emailError,
        userRolesError: userRolesError,
      });
      return;
    }

    await save(name, email, userRoles);
  }

  async function save(name, email, userRoles) {
    const buttons = [
      {
        type: "primary",
        key: "close",
        text: "Close",
        onClick: () => {
          navigate("/admin-users");
          navigate(0);
        },
      },
    ];

    setIsLoading(true);

    try {
      const apiBody = {
        userId: email,
        name: name,
        email: email,
        userRoles: userRoles,
        added_by: appParams.userId,
      };


      if (userToEdit) {
        await apiPut("PutUser", { user: apiBody, action: "update" });
        setIsLoading(false);
        requestClose();
        setDialog("Success", "User successfully updated.", buttons);
      } else {
        await apiPut("PutUser", { user: apiBody, action: "add" });
        setIsLoading(false);
        requestClose();
        setDialog("Success", "User successfully created.", buttons);
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

  if (!componentState) {
    return <> </>;
  }

  const selectedRole = componentState.userRoles[0];

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
            <Button
              appearance="subtle"
              icon={<FluentIcon name="Cancel" />}
              aria-label="Close"
              onClick={requestClose}
            />
          }
        >
          <span className="section-panel-title">
            <FluentIcon name="UserEvent" className="modal-icon" />
            {userToEdit ? "Edit User" : "New User"}
          </span>
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody>
        <div className="row mb-2">
          <div className="col-12">
            <Field label="Name" required validationMessage={componentState.nameError}>
              <Input
                value={componentState.name}
                onChange={(e, data) => onFormChange("name", data.value, setComponentState, componentState)}
              />
            </Field>
          </div>
        </div>
        <div className="row mb-2">
          <div className="col-12">
            <Field label="E-mail" required validationMessage={componentState.emailError}>
              <Input
                value={componentState.email}
                onChange={(e, data) => onFormChange("email", data.value, setComponentState, componentState)}
                disabled={userToEdit !== undefined}
              />
            </Field>
          </div>
        </div>
        <div className="row mb-4">
          <div className="col-12">
            <Field label="Type" required validationMessage={componentState.userRolesError}>
              <Dropdown
                placeholder="Select a type"
                selectedOptions={selectedRole ? [String(selectedRole)] : []}
                value={USER_ROLE_LABELS[selectedRole] || ""}
                onOptionSelect={(e, data) => onFormChange("userRoles", data.optionValue, setComponentState, componentState)}
              >
                <Option value="administrators">Administrator</Option>
                <Option value="contributors">Contributor</Option>
              </Dropdown>
            </Field>
          </div>
        </div>
        <div className="row">
          <div className="col-12 d-flex justify-content-end">
            <Button appearance="primary" className="me-2" onClick={validateBeforeSubmit}>Submit</Button>
            <Button onClick={requestClose}>Cancel</Button>
          </div>
        </div>
      </DrawerBody>
    </OverlayDrawer>
  );
};

export default CreateEditUserModal;
