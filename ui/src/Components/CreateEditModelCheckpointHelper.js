// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export async function createComponentDefaultState(modelId, imageLayerId, imagerySource, eventTypes, projectId) {
  try {


    const modelToEdit = null; // Placeholder for future edit functionality
    const tempState = modelToEdit
      ? {
        ...modelToEdit,
        baseModelNameError: "",
        userMetadataError: "",
      }
      : {
        modelId: modelId,
        projectId: projectId,
        imageLayerId: imageLayerId,
        imagerySource: imagerySource,
        eventTypes: eventTypes ? eventTypes : [],
        baseModelName: "",
        baseModelNameError: "",
        description: "",
        userMetadata: [],
        userMetadataError: "",
      }

    return tempState;
  } catch (error) {
    console.error("Error initializing component:", error);
  }

}

export const onFormChange = (value, key, setComponentState, componentState) => {
  setComponentState({ ...componentState, [key]: value });
};

export function addMetadata(setComponentState, componentState) {
  const tempMetadata = { key: "", value: "" };
  setComponentState({
    ...componentState,
    userMetadata: [...componentState.userMetadata, tempMetadata],
  });
}

export function removeMetadata(index, setComponentState, componentState) {
  setComponentState({
    ...componentState,
    userMetadata: componentState.userMetadata.filter(
      (c, i) => i !== index
    ),
  });
}

export function onChangeMetadata(index, key, value, setComponentState, componentState) {
  const tempUserMetadata = componentState.userMetadata.map((item, i) =>
    i === index ? { ...item, [key]: value } : item
  );
  setComponentState({
    ...componentState,
    userMetadata: tempUserMetadata,
  });
}