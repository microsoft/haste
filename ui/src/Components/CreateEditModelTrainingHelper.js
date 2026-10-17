// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import {
  buildBaseModelOptionKey,
  buildModelCatalogEndpoint,
} from "./BaseModelDropdownHelper.js";
import { hasCatalogCapability, readModelCatalog } from "./ModelCatalogHelper.js";

export async function fetchModelCatalog(imageLayer, eventTypes, get) {
  const response = await get(buildModelCatalogEndpoint(imageLayer, eventTypes));
  return readModelCatalog(response)
    .filter((model) => hasCatalogCapability(model, "training"))
    .map((model) => ({
      key: buildBaseModelOptionKey(model),
      text: model.baseModelName,
      value: model,
    }));
}

export function createComponentDefaultState(modelToEdit, imageLayer, projectId) {
  try {
    const tempState = modelToEdit
      ? {
        ...modelToEdit,
        nameError: "",
        viewParams: false,
        learningRateError: "",
        batchSizeError: "",
        maxEpochsError: "",
        cataloguedModels: [],
        catalogLoading: true,

      }
      : {
        modelId: "",
        projectId: projectId,
        imageLayerId: imageLayer.imageLayerId,
        name: imageLayer.name + "-model-" + Math.floor(Math.random() * 1000),
        nameError: "",
        autoRunInference: true,
        viewParams: false,
        learningRate: "0.0001",
        learningRateError: "",
        batchSize: "32",
        batchSizeError: "",
        maxEpochs: "3",
        maxEpochsError: "",
        baseModelId: "",
        baseModelIdError: "",
        initialWeightsUrl: "",
        cataloguedModels: [],
        catalogLoading: true,
      }

    return tempState;
  } catch (error) {
    console.error("Error inializing component:", error);
  }

}


export const onFormChange = (value, key, setComponentState, componentState) => {
  if (key === "viewParams") {
    setComponentState({
      ...componentState,
      viewParams: !componentState.viewParams,
    });
  } else {
    setComponentState({ ...componentState, [key]: value });
  }
};