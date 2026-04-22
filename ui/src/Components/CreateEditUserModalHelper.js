// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.



export async function createComponentDefaultState(userToEdit) {

  if (userToEdit) {
    if (!userToEdit.userRoles) {
      userToEdit.userRoles = [];
    }

    if (!userToEdit.name) {
      userToEdit.name = "";
    }
  }

  const tempState = userToEdit
    ? {
      ...userToEdit,
      nameError: "",
      emailError: "",
      userRolesError: "",
    }
    : {
      name: "",
      nameError: "",
      email: "",
      emailError: "",
      userRoles: [],
      userRolesError: ""
    };

  return tempState;
}



export function onFormChange(key, value, setComponentState, componentState) {

  if (key === "userRoles") {
    setComponentState({
      ...componentState,
      [key]: [value],
    });
  } else {

    setComponentState({
      ...componentState,
      [key]: value,
    });
  }
}
