// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { useEffect, useState, useContext } from "react";
import {
  getTheme,
  mergeStyleSets,
  FontWeights,
  Modal,
  TextField,
  FontIcon,
  Dropdown
} from "@fluentui/react";
import {
  DefaultButton,
  IconButton,
  PrimaryButton,
} from "@fluentui/react/lib/Button";


import { apiPut } from "../util/api";
import { useNavigate } from "react-router-dom";
import { AppContext } from "../AppContext";
import { createComponentDefaultState, onFormChange } from "./CreateEditUserModalHelper"
import { validateEmpty, validateEmail, validateAtLeastSomeNumber } from "../util/validation";
import proptypes from "prop-types";

const CreateEditUserModal = ({ onClose, userToEdit }) => {
  CreateEditUserModal.propTypes = {
    onClose: proptypes.func.isRequired,
    userToEdit: proptypes.object,
  };

  const { setDialog, setIsLoading, appParams } = useContext(AppContext);
  const navigate = useNavigate();
  const [componentState, setComponentState] = useState(null);

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
        onClose();
        setDialog("Success", "User successfully updated.", buttons);
      } else {
        await apiPut("PutUser", { user: apiBody, action: "add" });
        setIsLoading(false);
        onClose();
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

  return (
    <Modal
      titleAriaId={"Modal"}
      isOpen={true}
      onDismiss={onClose}
      isBlocking={true}
      containerClassName={contentStyles.container}
    >
      <div className={contentStyles.header}>
        <div className="d-flex align-items-center">
          <FontIcon iconName={"UserEvent"} className="me-2 modal-icon" />
          <p className={contentStyles.heading} id={"Modal"}>
            New User
          </p>
        </div>
        <IconButton
          styles={iconButtonStyles}
          iconProps={cancelIcon}
          ariaLabel="Close popup modal"
          onClick={onClose}
        />
      </div>
      <div className={`${contentStyles.body} modal-form-body`}>
        <div className="row mb-2">
          <div className="col-12">
            <TextField label="Name"
              required
              value={componentState.name}
              onChange={(e, value) => onFormChange("name", value, setComponentState, componentState)}
              errorMessage={componentState.nameError}
            />
          </div>
        </div>
        <div className="row mb-2">
          <div className="col-12">
            <TextField label="E-mail"
              required
              value={componentState.email}
              onChange={(e, value) => onFormChange("email", value, setComponentState, componentState)}
              errorMessage={componentState.emailError}
              disabled={userToEdit !== undefined}
            />
          </div>
        </div>
        <div className="row mb-4">
          <div className="col-12">
            <Dropdown
              required
              label="Type"
              placeholder="Select a type"
              value={componentState.userRoles[0]}
              defaultSelectedKey={componentState.userRoles[0]}
              onChange={(e, value) => onFormChange("userRoles", value.key, setComponentState, componentState)}
              errorMessage={componentState.userRolesError}
              options={[
                { key: "administrators", text: "Administrator" },
                { key: "contributors", text: "Contributor" },
              ]}
            />
          </div>
        </div>
        <div className="row">
          <div className="col-12 d-flex justify-content-end">
            <PrimaryButton className="me-2" onClick={validateBeforeSubmit}>Submit</PrimaryButton>
            <DefaultButton onClick={onClose}>Cancel</DefaultButton>
          </div>
        </div>
      </div>
    </Modal>
  );
};

const cancelIcon = { iconName: "Cancel" };

const theme = getTheme();
const contentStyles = mergeStyleSets({
  container: {
    display: "flex",
    flexFlow: "column nowrap",
    alignItems: "stretch",
  },
  header: [
    theme.fonts.xLargePlus,
    {
      flex: "1 1 auto",
      borderTop: `4px solid ${theme.palette.themePrimary}`,
      color: theme.palette.neutralPrimary,
      display: "flex",
      alignItems: "center",
      fontWeight: FontWeights.semibold,
      padding: "12px 12px 14px 24px",
    },
  ],
  heading: {
    color: theme.palette.neutralPrimary,
    fontWeight: FontWeights.semibold,
    fontSize: "20px",
    margin: "0",
  },
  body: {
    flex: "4 4 auto",
    padding: "0 24px 24px 24px",
    overflowY: "hidden",
    selectors: {
      p: { margin: "14px 0" },
      "p:first-child": { marginTop: 0 },
      "p:last-child": { marginBottom: 0 },
    },
  },
});

const iconButtonStyles = {
  root: {
    color: theme.palette.neutralPrimary,
    marginLeft: "auto",
    marginTop: "4px",
    marginRight: "2px",
  },
  rootHovered: {
    color: theme.palette.neutralDark,
  },
};

export default CreateEditUserModal;
